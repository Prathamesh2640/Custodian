"""Scan and clean engine. No Qt in here so it can be tested headless.

Guard rails enforced in this module (the UI cannot bypass them):
  * scanning is read-only; nothing is deleted until clean() is called with explicit items
  * every path is re-checked right before deletion, not only at scan time
  * drive roots, OS folders, Program Files, every account's profile and shell folders are refused
  * System32 / WinSxS / Installer / System Volume Information etc. are refused at any depth
  * paths that pass through a junction or symlink are refused; links found while
    deleting are never followed and never removed
  * deletions stay on the drive that was scanned; network and optical drives are not offered
  * rules whose app is running are skipped (re-checked at clean time)
  * per-rule minimum file age keeps files that are in use by installers
  * personal files (large/old files, duplicates) are only removed if size and timestamp
    still match the scan; at least one copy of every duplicate set is always kept
  * Recycle Bin mode is refused on drives that have no Recycle Bin (USB sticks)
  * long paths (>260 chars) are handled with the \\\\?\\ prefix
"""
import ctypes
import fnmatch
import glob
import hashlib
import heapq
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

import rules

REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
READONLY = stat.FILE_ATTRIBUTE_READONLY
SYSTEM = stat.FILE_ATTRIBUTE_SYSTEM
NO_WINDOW = subprocess.CREATE_NO_WINDOW

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")


class Cancelled(Exception):
    pass


class Stats:
    """Live counters. Worker threads write, the UI polls. Plain ints: torn reads only affect display."""

    def __init__(self):
        self.reset("")

    def reset(self, phase):
        self.phase = phase
        self.files = self.dirs = self.found = self.found_items = 0
        self.freed = self.moved = self.deleted = self.errors = 0
        self.current = ""
        self.started = time.monotonic()


_NULL_STATS = Stats()


# --------------------------------------------------------------------------- helpers

def fmt_size(b):
    for unit, div in (("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if abs(b) >= div:
            return f"{b / div:,.2f} {unit}" if unit in ("TB", "GB") else f"{b / div:,.1f} {unit}"
    return f"{b} B"


def lp(path):
    """Extended-length form so paths over 260 characters work."""
    return path if path.startswith("\\\\?\\") else "\\\\?\\" + os.path.abspath(path)


def unlp(path):
    return path[4:] if path.startswith("\\\\?\\") else path


def long_name(path):
    """Expand 8.3 short names (C:\\Users\\DELL~1) so comparisons are exact."""
    buf = ctypes.create_unicode_buffer(32768)
    n = kernel32.GetLongPathNameW(path, buf, len(buf))
    return buf.value if 0 < n < len(buf) else path


def norm(path):
    return os.path.normcase(os.path.normpath(long_name(path)))


def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin():
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
    else:
        exe, params = sys.executable, subprocess.list2cmdline([os.path.abspath(sys.argv[0])] + sys.argv[1:])
    return shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32


def running_processes():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}


def system_root():
    return os.environ.get("SystemDrive", "C:") + "\\"


DRIVE_KINDS = {2: "Removable", 3: "Local disk", 6: "RAM disk"}   # network (4) and optical (5) excluded


@dataclass
class Drive:
    root: str
    label: str
    fs: str
    kind: str
    total: int
    free: int

    @property
    def name(self):
        return self.label or self.kind

    def __str__(self):
        return f"{self.root[:2]}  {self.name}  -  {fmt_size(self.free)} free of {fmt_size(self.total)}"


def list_drives():
    kernel32.SetErrorMode(0x0001 | 0x8000)                   # no "insert a disk" popups for empty readers
    out, mask = [], kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask >> i & 1:
            continue
        root = f"{chr(65 + i)}:\\"
        kind = DRIVE_KINDS.get(kernel32.GetDriveTypeW(root))
        if not kind:
            continue
        try:
            total, _, free = shutil.disk_usage(root)
        except OSError:
            continue
        label, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
        kernel32.GetVolumeInformationW(root, label, 261, None, None, None, fs, 261)
        out.append(Drive(root, label.value, fs.value, kind, total, free))
    return out


def free_space(root):
    return shutil.disk_usage(root).free


def has_recycle_bin(root):
    """Only fixed disks get a Recycle Bin; on USB sticks 'recycle' silently means delete."""
    return kernel32.GetDriveTypeW(root[:2] + "\\") == 3


# --------------------------------------------------------------------------- accounts

USER_VARS = ("%USERPROFILE%", "%LOCALAPPDATA%", "%APPDATA%", "%TEMP%")
USER_SIDS = ("S-1-5-21-", "S-1-12-1-")   # local/domain accounts and Microsoft Entra (Azure AD) accounts


@dataclass
class Profile:
    name: str
    path: str
    env: dict            # USER_VARS -> folder for this account
    current: bool


def user_profiles(all_users=True):
    """Current account first, then every other real account from the registry ProfileList."""
    env = os.environ
    cur = env.get("USERPROFILE", "")
    out = [Profile(os.path.basename(cur), cur, {
        "%USERPROFILE%": cur, "%LOCALAPPDATA%": env.get("LOCALAPPDATA", ""),
        "%APPDATA%": env.get("APPDATA", ""), "%TEMP%": env.get("TEMP", "")}, True)]
    if not all_users:
        return out
    seen = {norm(cur)}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList") as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                sid = winreg.EnumKey(k, i)
                if not sid.startswith(USER_SIDS):
                    continue
                try:
                    with winreg.OpenKey(k, sid) as sk:
                        home = os.path.expandvars(winreg.QueryValueEx(sk, "ProfileImagePath")[0])
                except OSError:
                    continue
                if norm(home) in seen or not os.path.isdir(home):
                    continue
                seen.add(norm(home))
                local = os.path.join(home, "AppData", "Local")
                out.append(Profile(os.path.basename(home), home, {
                    "%USERPROFILE%": home, "%LOCALAPPDATA%": local,
                    "%APPDATA%": os.path.join(home, "AppData", "Roaming"),
                    "%TEMP%": os.path.join(local, "Temp")}, False))
    except OSError:
        pass
    return out


def _profile_folders(p):
    """Folders inside an account that must never be deleted wholesale."""
    home, local, roaming = p.env["%USERPROFILE%"], p.env["%LOCALAPPDATA%"], p.env["%APPDATA%"]
    return [home, os.path.join(home, "AppData"), local, roaming, os.path.join(home, "AppData", "LocalLow"),
            os.path.dirname(p.env["%TEMP%"]), os.path.join(local, "Google"),
            os.path.join(local, "Google", "Chrome", "User Data"), os.path.join(local, "Microsoft"),
            os.path.join(local, "Programs"), os.path.join(local, "Packages"), os.path.join(roaming, "Microsoft"),
            *(os.path.join(home, n) for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music",
                                             "OneDrive", "Favorites", "Contacts", "Links", "Saved Games",
                                             "Searches", "3D Objects"))]


def _shell_folders():
    paths = []
    for key in (r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                i = 0
                while True:
                    try:
                        _, value, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if isinstance(value, str) and ":" in os.path.expandvars(value):
                        paths.append(os.path.expandvars(value))
        except OSError:
            pass
    return paths


# --------------------------------------------------------------------------- guard rails

class Guard:
    """Decides whether a path may be deleted. Every deletion calls check() first."""

    TOP_TREES = ("System Volume Information", "$Recycle.Bin", "Recovery", "Boot", "EFI", "Config.Msi",
                 "$WinREAgent", "$SysReset", "$Windows.~BT", "$Windows.~WS", "WindowsApps",
                 "Program Files\\WindowsApps")
    WIN_TREES = ("System32", "SysWOW64", "WinSxS", "Installer", "servicing", "assembly", "Microsoft.NET",
                 "Fonts", "Boot", "SystemApps", "SystemResources", "ImmersiveControlPanel", "INF",
                 "PolicyDefinitions")

    def __init__(self, root):
        self.root = norm(root)
        if not self.root.endswith("\\"):
            self.root += "\\"
        env = os.environ
        windir = env.get("SystemRoot", r"C:\Windows")
        exact = [
            self.root, windir, env.get("ProgramFiles", ""), env.get("ProgramFiles(x86)", ""),
            env.get("ProgramData", ""), env.get("PUBLIC", ""), os.path.dirname(env.get("USERPROFILE", "")),
            env.get("OneDrive", ""),
            *(f for p in user_profiles() for f in _profile_folders(p)),   # every account, always
            *(os.path.join(self.root, n) for n in ("Windows", "Program Files", "Program Files (x86)",
                                                  "ProgramData", "Users")),
            *_shell_folders(),
        ]
        self.exact = {norm(p) for p in exact if p}
        trees = [os.path.join(self.root, t) for t in self.TOP_TREES]
        trees += [os.path.join(windir, t) for t in self.WIN_TREES]
        self.trees = {norm(t) for t in trees}

    def check(self, path, is_file=False):
        """Return None if deletable, else the reason it is refused."""
        if not path or not os.path.isabs(path) or path.startswith("\\\\"):
            return "not an absolute local path"
        p = norm(path)
        if not p.startswith(self.root):
            return "outside the selected drive"
        depth = len([s for s in p[len(self.root):].split("\\") if s])
        if depth < (1 if is_file else 2):
            return "too close to the drive root"
        if p in self.exact:
            return "protected folder"
        for t in self.trees:
            if p == t or p.startswith(t + "\\"):
                return "inside a protected system area"
        if norm(unlp(os.path.realpath(path))) != p:
            return "path goes through a junction or symlink"
        try:
            if os.lstat(lp(path)).st_file_attributes & REPARSE:
                return "path is a junction or symlink"
        except OSError:
            pass
        return None


# --------------------------------------------------------------------------- tree walking

def walk(top, cancel=None):
    """Post-order walk yielding (path, kind, stat). kind is file|dir|link.

    Iterative (no recursion limit), long-path safe, never enters reparse points.
    The top folder itself is yielded last as a dir.
    """
    top = lp(top)
    try:
        stack = [(top, os.scandir(top))]
    except OSError:
        return
    while stack:
        path, it = stack[-1]
        if cancel is not None and cancel.is_set():
            for _, i in stack:
                i.close()
            raise Cancelled
        try:
            entry = next(it, None)
        except OSError:
            entry = None
        if entry is None:
            it.close()
            stack.pop()
            yield path, "dir", None
            continue
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if st.st_file_attributes & REPARSE:
            yield entry.path, "link", st
        elif stat.S_ISDIR(st.st_mode):
            try:
                stack.append((entry.path, os.scandir(entry.path)))
            except OSError:
                pass
        else:
            yield entry.path, "file", st


def measure(path, cancel=None, min_age=0, stats=_NULL_STATS):
    """(bytes, files) under path, respecting min_age in hours."""
    cutoff = time.time() - min_age * 3600
    try:
        st = os.lstat(lp(path))
    except OSError:
        return 0, 0
    if not stat.S_ISDIR(st.st_mode):
        stats.files += 1
        return (st.st_size, 1) if not min_age or st.st_mtime <= cutoff else (0, 0)
    size = files = 0
    stats.current = path
    for _, kind, st in walk(path, cancel):
        if kind == "file":
            stats.files += 1
            if not min_age or st.st_mtime <= cutoff:
                size += st.st_size
                files += 1
        elif kind == "dir":
            stats.dirs += 1
    return size, files


def _unlink(path, st):
    if st.st_file_attributes & READONLY:
        os.chmod(path, stat.S_IWRITE)
    os.unlink(path)


def delete_tree(path, keep_root, cancel=None, min_age=0, on_error=None, stats=_NULL_STATS):
    """Delete files under path. Returns (bytes_freed, files_deleted, errors)."""
    cutoff = time.time() - min_age * 3600
    top = lp(path)
    freed = files = errors = 0
    stats.current = path
    for p, kind, st in walk(path, cancel):
        if kind == "link":
            continue                        # never follow or remove links
        if kind == "file":
            if min_age and st.st_mtime > cutoff:
                continue
            try:
                _unlink(p, st)
                freed += st.st_size
                files += 1
                stats.freed += st.st_size
                stats.deleted += 1
            except OSError as e:
                errors += 1
                stats.errors += 1
                if on_error:
                    on_error(unlp(p), e.strerror or str(e))
        elif not (keep_root and p == top):
            try:
                os.rmdir(p)
            except OSError:
                pass                        # not empty: something was kept or locked
    return freed, files, errors


def delete_file(path, min_age=0):
    st = os.lstat(lp(path))
    if st.st_file_attributes & REPARSE or stat.S_ISDIR(st.st_mode):
        raise OSError("not a regular file")
    if min_age and st.st_mtime > time.time() - min_age * 3600:
        return 0
    _unlink(lp(path), st)
    return st.st_size


# --------------------------------------------------------------------------- Recycle Bin

class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]


def recycle_bin_size(root):
    info = SHQUERYRBINFO(cbSize=ctypes.sizeof(SHQUERYRBINFO))
    if shell32.SHQueryRecycleBinW(root, ctypes.byref(info)) != 0:
        return 0, 0
    return info.i64Size, info.i64NumItems


def empty_recycle_bin(root):
    hr = shell32.SHEmptyRecycleBinW(None, root, 0x1 | 0x2 | 0x4)   # no confirm, no progress, no sound
    return hr in (0, -2147418113)                                      # S_OK or E_UNEXPECTED (already empty)


def _shell_recycle(batch):
    buf = ctypes.create_unicode_buffer("\0".join(batch) + "\0")   # the buffer adds the final NUL
    # silent, no confirmation, allow undo, no error UI; FOF_WANTNUKEWARNING asks before permanently
    # deleting something too big for the bin instead of doing that silently
    op = SHFILEOPSTRUCTW(wFunc=3, pFrom=ctypes.cast(buf, ctypes.c_wchar_p), fFlags=0x4 | 0x10 | 0x40 | 0x400 | 0x4000)
    shell32.SHFileOperationW(ctypes.byref(op))
    return [b for b in batch if os.path.lexists(b)]


def send_to_recycle_bin(paths):
    """Recycle many paths in few shell calls. Returns the paths that still exist afterwards."""
    ole32.CoInitializeEx(None, 0x2)
    left, batch, chars = [], [], 0
    for p in paths:
        if batch and (len(batch) >= 500 or chars + len(p) > 30000):
            left += _shell_recycle(batch)
            batch, chars = [], 0
        batch.append(p)
        chars += len(p) + 1
    if batch:
        left += _shell_recycle(batch)
    return left


# --------------------------------------------------------------------------- results

@dataclass
class Item:
    rule: dict
    paths: list
    size: int = 0
    files: int = 0
    blocked: str = ""
    mtime: float = 0.0
    user: str = ""            # account name, set when several accounts were scanned
    other_user: bool = False  # belongs to an account other than the one running the app
    group: int = 0            # duplicate set id
    peers: list = field(default_factory=list)   # every path in the duplicate set

    @property
    def label(self):
        return f"{self.rule['label']}  [{self.user}]" if self.user else self.rule["label"]

    @property
    def where(self):
        return self.paths[0] if len(self.paths) == 1 else f"{len(self.paths):,} locations on this drive"


@dataclass
class ScanResult:
    root: str
    items: list = field(default_factory=list)
    errors: int = 0
    seconds: float = 0.0


RECYCLE_RULE = rules.R("recycle_bin", "Recycle Bin", "Recycle Bin on this drive", [], action="recyclebin",
                       note="Emptied through Windows, same as right-click > Empty Recycle Bin.")
FILE_RULE = rules.R("user_file", "Files", "File", [], action="userfile", risk=rules.REVIEW)
DUP_RULE = rules.R("duplicate", "Duplicates", "Duplicate copy", [], action="userfile", risk=rules.REVIEW)
NODE_RULE = next(r for r in rules.DEEP_RULES if r["id"] == "node_modules")

TOP_PRUNE = {"windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
             "system volume information", "recovery", "config.msi", "boot", "efi", "$winreagent",
             "$sysreset", "$windows.~bt", "$windows.~ws", "windowsapps", "msocache", "perflogs"}
ANY_PRUNE = {"appdata", "windowsapps", "$recycle.bin"}
APP_DIRS = {"resources", "program files", "program files (x86)", "extensions"}


def expand(template, profile=None):
    """Expand %VARS% (per-user ones from profile) and * wildcards. Returns existing paths only."""
    p = template
    if profile:
        for var, value in profile.env.items():
            p = re.sub(re.escape(var), lambda _m, v=value: v, p, flags=re.I)
    p = os.path.expandvars(p)
    if "%" in p:
        return []
    if "*" not in p:
        return [p] if os.path.lexists(p) else []
    drive, rest = os.path.splitdrive(p)
    parts = [s if "*" in s else glob.escape(s) for s in rest.split("\\")]
    return sorted(glob.glob(drive + "\\".join(parts), include_hidden=True))


def is_user_rule(rule):
    return any(v in t.upper() for t in rule["paths"] for v in USER_VARS)


def _node_modules_ok(path):
    parent = os.path.dirname(path)
    parts = [s.lower() for s in parent.split("\\")]
    if any(s.startswith(".") or s in APP_DIRS or s == "node_modules" for s in parts):
        return False
    return os.path.isfile(os.path.join(parent, "package.json"))


def iter_drive(start, cancel, stats=_NULL_STATS, on_dir=None):
    """Yield (path, stat) for every regular file under start, skipping OS/app areas and links.

    on_dir(path, lower_name) may return True to not descend into that folder.
    """
    start_n = norm(start).rstrip("\\") + "\\"
    stack = [lp(start)]
    while stack:
        if cancel.is_set():
            raise Cancelled
        folder = stack.pop()
        stats.dirs += 1
        stats.current = unlp(folder)
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            stats.errors += 1
            continue
        top_level = norm(unlp(folder)).rstrip("\\") + "\\" == start_n
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if st.st_file_attributes & REPARSE:
                continue
            if stat.S_ISDIR(st.st_mode):
                name = e.name.lower()
                if name in ANY_PRUNE or (top_level and (name in TOP_PRUNE or name.startswith("$"))):
                    continue
                if on_dir and on_dir(unlp(e.path), name):
                    continue
                stack.append(e.path)
            else:
                stats.files += 1
                yield unlp(e.path), st


# --------------------------------------------------------------------------- junk scan

def scan(root, guard, cancel, progress=lambda text, frac=None: None, deep=True, admin=None,
         all_users=False, stats=_NULL_STATS):
    """Read-only. Builds the list of junk that could be cleaned.

    all_users only takes effect as admin: other accounts' AppData is unreadable otherwise.
    """
    admin = is_admin() if admin is None else admin
    running = running_processes()
    res = ScanResult(root)
    t0 = time.monotonic()

    def add(item):
        res.items.append(item)
        stats.found += item.size
        stats.found_items += 1

    size, count = recycle_bin_size(root)
    if size:
        add(Item(RECYCLE_RULE, [root], size, count))

    if norm(root) == norm(system_root()):
        profiles = [p for p in user_profiles(all_users and admin) if norm(p.path).startswith(guard.root)]
        many = len(profiles) > 1
        jobs = [(r, p) for r in rules.SYSTEM_RULES for p in (profiles if is_user_rule(r) else [None])]
        for n, (rule, prof) in enumerate(jobs):
            who = f" for {prof.name}" if prof and many else ""
            progress(f"Checking {rule['label']}{who}", n / len(jobs) * (0.4 if deep else 1))
            paths = [p for t in rule["paths"] for p in expand(t, prof)
                     if not guard.check(p, is_file=rule["action"] == "files")]
            if not paths:
                continue
            item = Item(rule, paths, user=prof.name if prof and many else "",
                        other_user=bool(prof and not prof.current))
            for p in paths:
                s, f = measure(p, cancel, rule["min_age"], stats)
                item.size += s
                item.files += f
            if item.size <= 0:
                continue
            busy = sorted(set(rule["procs"]) & running)
            if (rule["admin"] or item.other_user) and not admin:
                item.blocked = "Needs administrator"
            elif busy:
                item.blocked = "Close " + ", ".join(busy) + " first"
            add(item)

    if deep:
        progress(f"Searching {root} for project and system leftovers", None)
        before = len(res.items)
        _deep_scan(root, guard, cancel, res, stats)
        stats.found += sum(i.size for i in res.items[before:])
        stats.found_items += len(res.items) - before
    res.seconds = time.monotonic() - t0
    progress("Scan complete", 1.0)
    return res


def _deep_scan(start, guard, cancel, res, stats=_NULL_STATS):
    dir_rules = {n.lower(): r for r in rules.DEEP_RULES if r["action"] == "tree" for n in r["paths"]}
    file_rules = [(n.lower(), r) for r in rules.DEEP_RULES if r["action"] == "files" for n in r["paths"]]
    found = {r["id"]: Item(r, []) for r in rules.DEEP_RULES if r["id"] != "node_modules"}
    claimed = {norm(p) for i in res.items for p in i.paths}   # already covered by a system rule
    node_modules = []
    now = time.time()

    def on_dir(path, name):
        if claimed and os.path.normcase(path) in claimed:
            return True
        rule = dir_rules.get(name)
        if not rule or guard.check(path):
            return False
        if rule["id"] == "node_modules":
            if not _node_modules_ok(path):
                return False
            node_modules.append(path)
        else:
            found[rule["id"]].paths.append(path)
        return True

    for path, st in iter_drive(start, cancel, stats, on_dir):
        if st.st_file_attributes & SYSTEM:
            continue
        name = os.path.basename(path).lower()
        for pattern, rule in file_rules:
            if fnmatch.fnmatchcase(name, pattern):
                if (not rule["min_age"] or st.st_mtime <= now - rule["min_age"] * 3600) \
                        and os.path.normcase(path) not in claimed and not guard.check(path, is_file=True):
                    it = found[rule["id"]]
                    it.paths.append(path)
                    it.size += st.st_size
                    it.files += 1
                break

    for rule_id, item in found.items():
        if item.rule["action"] == "tree":
            for p in item.paths:
                s, f = measure(p, cancel, stats=stats)
                item.size += s
                item.files += f
    for p in node_modules:
        s, f = measure(p, cancel, stats=stats)
        if s:
            res.items.append(Item(NODE_RULE, [p], s, f))
    res.items.extend(i for i in found.values() if i.size > 0)


# --------------------------------------------------------------------------- personal files

def scan_files(root, guard, cancel, min_mb=100, older_days=0, limit=2000, stats=_NULL_STATS):
    """Largest files at least min_mb big and (optionally) untouched for older_days."""
    t0 = time.monotonic()
    min_size = min_mb * (1 << 20)
    cutoff = time.time() - older_days * 86400
    heap = []
    for path, st in iter_drive(root, cancel, stats):
        if st.st_size < min_size or st.st_file_attributes & SYSTEM:
            continue
        if older_days and st.st_mtime > cutoff:
            continue
        if guard.check(path, is_file=True):
            continue
        entry = (st.st_size, path, st.st_mtime)
        if len(heap) < limit:
            heapq.heappush(heap, entry)
            stats.found += st.st_size
            stats.found_items += 1
        elif entry > heap[0]:
            stats.found += st.st_size - heap[0][0]
            heapq.heapreplace(heap, entry)
    res = ScanResult(root, [Item(FILE_RULE, [p], s, 1, mtime=m) for s, p, m in sorted(heap, reverse=True)])
    res.errors, res.seconds = stats.errors, time.monotonic() - t0
    return res


DUP_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "site-packages", ".gradle", ".m2"}


def _digest(path, limit, cancel):
    h = hashlib.blake2b(digest_size=20)
    left = limit
    with open(lp(path), "rb") as f:
        while left:
            if cancel.is_set():
                raise Cancelled
            chunk = f.read(min(1 << 20, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    return h.digest()


def find_duplicates(root, guard, cancel, min_mb=1, progress=lambda text, frac=None: None, stats=_NULL_STATS):
    """Files with identical content: grouped by size, then first 64 KB hash, then full hash.

    Hard links to the same file are not duplicates (deleting one frees nothing) and are merged.
    """
    t0 = time.monotonic()
    min_size = max(1, int(min_mb * (1 << 20)))
    by_size = {}
    progress("Listing files", None)
    for path, st in iter_drive(root, cancel, stats, lambda p, n: n in DUP_SKIP_DIRS):
        if st.st_size >= min_size and not st.st_file_attributes & SYSTEM:
            by_size.setdefault(st.st_size, []).append((path, st.st_mtime))

    candidates = [(s, v) for s, v in by_size.items() if len(v) > 1]
    total = sum(s * len(v) for s, v in candidates) or 1
    done = 0
    groups = []
    for size, files in sorted(candidates, reverse=True):
        # merge hard links (same volume serial + file index)
        uniq = {}
        for path, mtime in files:
            try:
                st = os.stat(lp(path))
            except OSError:
                continue
            uniq.setdefault((st.st_dev, st.st_ino) if st.st_ino else path, (path, mtime))
        files = list(uniq.values())
        if len(files) < 2:
            continue
        for limit in (64 * 1024, size):                # quick pass, then full content
            buckets = {}
            for path, mtime in files:
                stats.current = path
                try:
                    buckets.setdefault(_digest(path, limit, cancel), []).append((path, mtime))
                except OSError:
                    stats.errors += 1
            files = [f for b in buckets.values() if len(b) > 1 for f in b]
            if limit == size or size <= limit:
                groups += [(size, b) for b in buckets.values() if len(b) > 1]
                break
        done += size * len(files)
        progress(f"Comparing files of {fmt_size(size)}", min(done / total, 1.0))

    res = ScanResult(root)
    for gid, (size, members) in enumerate(sorted(groups, key=lambda g: -g[0] * (len(g[1]) - 1)), 1):
        peers = [p for p, _ in members]
        for path, mtime in sorted(members, key=lambda m: m[1]):     # oldest first
            if guard.check(path, is_file=True):
                continue
            res.items.append(Item(DUP_RULE, [path], size, 1, mtime=mtime, group=gid, peers=peers))
        stats.found += size * (len(members) - 1)
        stats.found_items += len(members) - 1
    res.errors, res.seconds = stats.errors, time.monotonic() - t0
    progress("Duplicate search complete", 1.0)
    return res


# --------------------------------------------------------------------------- clean

def _recycle_targets(path, action, min_age, cancel):
    """What to hand to the Recycle Bin for one target path."""
    if action != "contents":
        return [path]
    if not min_age:
        try:
            with os.scandir(lp(path)) as it:
                return [unlp(e.path) for e in it if not e.stat(follow_symlinks=False).st_file_attributes & REPARSE]
        except OSError:
            return []
    cutoff = time.time() - min_age * 3600
    return [unlp(p) for p, kind, st in walk(path, cancel) if kind == "file" and st.st_mtime <= cutoff]


def clean(items, guard, cancel, progress=lambda text, frac=None: None, log=print, recycle=False,
          stats=_NULL_STATS):
    """Delete (or recycle) the given items. Re-validates everything first. Returns a summary dict."""
    admin = is_admin()
    running = running_processes()
    out = dict(freed=0, moved=0, files=0, errors=0, refused=0, skipped=0)
    items = list(items)

    if recycle and not has_recycle_bin(guard.root):
        log(f"REFUSED: {guard.root} has no Recycle Bin (removable drive). Choose Permanent delete instead.")
        out["refused"] = len(items)
        return out

    # duplicates: never remove every copy
    selected = {os.path.normcase(i.paths[0]) for i in items if i.group}
    by_group = {}
    for i in items:
        if i.group:
            by_group.setdefault(i.group, []).append(i)
    for members in by_group.values():
        if len(members) >= len(members[0].peers):
            keep = min(members, key=lambda i: i.mtime)
            items.remove(keep)
            selected.discard(os.path.normcase(keep.paths[0]))
            log(f"KEPT {keep.paths[0]}: every copy was selected, the oldest one is always kept")

    def err(path, why):
        out["errors"] += 1
        stats.errors += 1
        if out["errors"] <= 200:
            log(f"    could not remove {path}: {why}")

    total = sum(i.size for i in items) or 1
    done = 0
    for item in items:
        if cancel.is_set():
            log("Stopped by user.")
            break
        rule = item.rule
        progress(f"{'Recycling' if recycle else 'Deleting'} {item.label}", done / total)
        busy = sorted(set(rule["procs"]) & running)
        if busy:
            log(f"SKIPPED {item.label}: {', '.join(busy)} is running")
            out["skipped"] += 1
            continue
        if (rule["admin"] or item.other_user) and not admin:
            log(f"SKIPPED {item.label}: needs administrator")
            out["skipped"] += 1
            continue

        action = rule["action"]
        before = (out["freed"] + out["moved"], out["files"], out["errors"])
        try:
            if action == "recyclebin":
                if norm(item.paths[0]) != guard.root:
                    log(f"REFUSED Recycle Bin {item.paths[0]}: not the scanned drive")
                    out["refused"] += 1
                elif empty_recycle_bin(guard.root):
                    out["freed"] += item.size
                    out["files"] += item.files
                    stats.freed += item.size
                    stats.deleted += item.files
                else:
                    err(guard.root, "Windows could not empty the Recycle Bin")
            else:
                for p in item.paths:
                    if cancel.is_set():
                        break
                    stats.current = p
                    why = guard.check(p, is_file=action in ("files", "userfile"))
                    if why:
                        log(f"REFUSED {p}: {why}")
                        out["refused"] += 1
                        continue
                    if action == "userfile":
                        _clean_user_file(item, p, selected, recycle, out, stats, log, err)
                    elif recycle:
                        size, n = measure(p, cancel, rule["min_age"])
                        if action == "files" and not n:
                            continue
                        left = send_to_recycle_bin(_recycle_targets(p, action, rule["min_age"], cancel))
                        remaining = measure(p, cancel, rule["min_age"])[0] if os.path.lexists(p) else 0
                        out["moved"] += size - remaining
                        stats.moved += size - remaining
                        out["files"] += n
                        stats.deleted += n
                        for x in left[:50]:
                            err(x, "in use or could not be recycled")
                    elif action == "files":
                        try:
                            size = delete_file(p, rule["min_age"])
                            out["freed"] += size
                            out["files"] += 1
                            stats.freed += size
                            stats.deleted += 1
                        except FileNotFoundError:
                            pass
                        except OSError as e:
                            err(p, e.strerror or str(e))
                    else:
                        f, n, _ = delete_tree(p, keep_root=action == "contents", cancel=cancel,
                                              min_age=rule["min_age"], on_error=err, stats=stats)
                        out["freed"] += f
                        out["files"] += n
        except Cancelled:
            log("Stopped by user.")
            break
        gained = out["freed"] + out["moved"] - before[0]
        log(f"{'RECYCLED' if recycle and action != 'recyclebin' else 'CLEANED'} {item.label}: "
            f"{fmt_size(gained)} in {out['files'] - before[1]:,} files, "
            f"{out['errors'] - before[2]:,} locked/denied  [{item.where}]")
        done += item.size
    progress("Done", 1.0)
    return out


def _clean_user_file(item, p, selected, recycle, out, stats, log, err):
    try:
        st = os.lstat(lp(p))
    except OSError:
        return
    if st.st_size != item.size or abs(st.st_mtime - item.mtime) > 2:
        log(f"SKIPPED {p}: file changed since the scan")
        out["skipped"] += 1
        return
    if item.group:
        survivors = [q for q in item.peers if os.path.normcase(q) not in selected and _same_size(q, item.size)]
        if not survivors:
            log(f"KEPT {p}: no other copy of this file would remain")
            out["skipped"] += 1
            return
    if recycle:
        if send_to_recycle_bin([p]):
            err(p, "Recycle Bin operation failed or was cancelled")
            return
        out["moved"] += st.st_size
        stats.moved += st.st_size
    else:
        try:
            _unlink(lp(p), st)
        except OSError as e:
            err(p, e.strerror or str(e))
            return
        out["freed"] += st.st_size
        stats.freed += st.st_size
    out["files"] += 1
    stats.deleted += 1


def _same_size(path, size):
    try:
        return os.lstat(lp(path)).st_size == size
    except OSError:
        return False


# --------------------------------------------------------------------------- system tools

def system_file_size(name, root=None):
    """Size of hiberfil.sys / pagefile.sys from the directory listing (they cannot be opened)."""
    try:
        with os.scandir(root or system_root()) as it:
            for e in it:
                if e.name.lower() == name.lower():
                    return e.stat(follow_symlinks=False).st_size
    except OSError:
        pass
    return 0


def run_command(args, log, on_start=None):
    """Run a system tool, streaming its output to log. Returns the exit code."""
    log("> " + subprocess.list2cmdline(args))
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=NO_WINDOW, encoding="oem", errors="replace")
    except OSError as e:
        log(f"    could not start: {e.strerror or e}")
        return -1
    if on_start:
        on_start(proc)
    for line in proc.stdout:
        line = line.strip()
        if line:
            log("    " + line)
    return proc.wait()
