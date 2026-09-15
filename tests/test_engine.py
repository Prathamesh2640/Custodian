"""Guard-rail and deletion self-check. Run: .venv\\Scripts\\python tests\\test_engine.py"""
import os
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import engine  # noqa: E402


def main():
    sysroot = engine.system_root()
    g = engine.Guard(sysroot)
    home = os.environ["USERPROFILE"]

    # --- guard refuses the dangerous stuff
    for p in (sysroot, os.environ["SystemRoot"], os.path.join(os.environ["SystemRoot"], "System32", "drivers"),
              os.path.join(os.environ["SystemRoot"], "WinSxS", "x"), home, os.path.join(home, "Downloads"),
              os.path.join(home, "Documents"), os.environ["LOCALAPPDATA"], os.environ["ProgramFiles"],
              os.path.join(sysroot, "System Volume Information", "x"), "relative\\path", r"\\server\share\x"):
        assert g.check(p), f"guard allowed {p}"
    assert g.check(r"Z:\some\folder") == "outside the selected drive"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = engine.long_name(tmp)
        assert g.check(os.path.join(tmp, "cache")) is None, g.check(os.path.join(tmp, "cache"))

        # --- sandbox: files, read-only file, fresh file, long path, junction to a sentinel
        cache = os.path.join(tmp, "cache")
        sentinel = os.path.join(tmp, "precious")
        os.makedirs(os.path.join(cache, "sub"))
        os.makedirs(sentinel)
        open(os.path.join(sentinel, "keep.txt"), "w").write("do not delete")
        for name in ("a.bin", "sub\\b.bin"):
            with open(os.path.join(cache, name), "wb") as f:
                f.write(b"x" * 1000)
        ro = os.path.join(cache, "ro.bin")
        open(ro, "wb").write(b"y" * 10)
        os.chmod(ro, 0o444)
        deep = engine.lp(os.path.join(cache, *(["d" * 50] * 7)))
        os.makedirs(deep)
        open(os.path.join(deep, "long.bin"), "wb").write(b"z" * 5)
        assert len(deep) > 300
        subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(cache, "link"), sentinel],
                       check=True, capture_output=True)
        old = time.time() - 3 * 86400
        for p, _, _ in engine.walk(cache):
            if not os.path.isdir(p):
                os.utime(p, (old, old))
        fresh = os.path.join(cache, "fresh.bin")
        open(fresh, "wb").write(b"f" * 7)

        assert g.check(os.path.join(cache, "link")), "junction itself must be refused"
        assert g.check(os.path.join(cache, "link", "keep.txt")), "path through junction must be refused"

        size, files = engine.measure(cache, min_age=24)
        assert (size, files) == (2015, 4), (size, files)

        freed, n, errors = engine.delete_tree(cache, keep_root=True, min_age=24)
        assert (freed, n, errors) == (2015, 4, 0), (freed, n, errors)
        assert os.path.exists(os.path.join(sentinel, "keep.txt")), "junction target was touched"
        assert os.path.exists(fresh), "min_age did not protect a fresh file"
        assert os.path.isdir(cache) and not os.path.exists(os.path.join(cache, "sub"))

        # --- cancel stops a walk
        ev = threading.Event()
        ev.set()
        try:
            list(engine.walk(tmp, ev))
            raise AssertionError("cancel ignored")
        except engine.Cancelled:
            pass

        # --- deep scan finds pycache / node_modules only in eligible places
        proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(proj, "node_modules", "left-pad"))
        open(os.path.join(proj, "package.json"), "w").write("{}")
        open(os.path.join(proj, "node_modules", "left-pad", "index.js"), "w").write("x" * 50)
        os.makedirs(os.path.join(tmp, ".vscode", "ext", "node_modules"))
        open(os.path.join(tmp, ".vscode", "ext", "package.json"), "w").write("{}")
        open(os.path.join(tmp, ".vscode", "ext", "node_modules", "i.js"), "w").write("x")
        os.makedirs(os.path.join(proj, "__pycache__"))
        open(os.path.join(proj, "__pycache__", "m.pyc"), "wb").write(b"p" * 20)
        res = engine.ScanResult(sysroot)
        engine._deep_scan(tmp, g, threading.Event(), res)
        got = {i.rule["id"]: i for i in res.items}
        assert got["node_modules"].paths == [os.path.join(proj, "node_modules")], got["node_modules"].paths
        assert got["pycache"].size == 20

        out = engine.clean(res.items, g, threading.Event(), log=lambda m: None)
        assert out["refused"] == 0 and out["errors"] == 0, out
        assert not os.path.exists(os.path.join(proj, "node_modules"))
        assert os.path.exists(os.path.join(tmp, ".vscode", "ext", "node_modules", "i.js"))

        # --- clean re-checks guard: a forged item pointing at a protected folder is refused
        forged = engine.Item(dict(res.items[0].rule, action="contents", procs=[], admin=False), [home])
        out = engine.clean([forged], g, threading.Event(), log=lambda m: None)
        assert out["refused"] == 1 and out["freed"] == 0, out

    # --- other accounts: their profile folders are protected, their caches expand per account
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(engine.long_name(tmp), "OtherUser")
        local = os.path.join(home, "AppData", "Local")
        os.makedirs(os.path.join(local, "Temp"))
        os.makedirs(os.path.join(local, "CrashDumps"))
        fake = engine.Profile("OtherUser", home, {
            "%USERPROFILE%": home, "%LOCALAPPDATA%": local,
            "%APPDATA%": os.path.join(home, "AppData", "Roaming"), "%TEMP%": os.path.join(local, "Temp")}, False)
        real = engine.user_profiles
        engine.user_profiles = lambda all_users=True: real(False) + [fake]
        try:
            g2 = engine.Guard(sysroot)
        finally:
            engine.user_profiles = real
        for p in (home, local, os.path.join(home, "Documents"), os.path.join(home, "AppData")):
            assert g2.check(p) == "protected folder", (p, g2.check(p))
        assert g2.check(os.path.join(local, "Temp")) is None
        rule = next(r for r in engine.rules.SYSTEM_RULES if r["id"] == "crashdumps")
        assert engine.is_user_rule(rule)
        assert not engine.is_user_rule(next(r for r in engine.rules.SYSTEM_RULES if r["id"] == "win_temp"))
        assert engine.expand(rule["paths"][0], fake) == [os.path.join(local, "CrashDumps")]
        assert engine.user_profiles(False)[0].current and len(engine.user_profiles(False)) == 1

    # --- duplicates: content match, and one copy always survives even if every copy is selected
    with tempfile.TemporaryDirectory() as tmp:
        tmp = engine.long_name(tmp)
        blob = os.urandom(200_000)
        copies = []
        for n in range(3):
            d = os.path.join(tmp, f"folder{n}")
            os.makedirs(d)
            copies.append(os.path.join(d, "photo.jpg"))
            open(copies[-1], "wb").write(blob)
            os.utime(copies[-1], (time.time() - (3 - n) * 86400,) * 2)
        open(os.path.join(tmp, "folder0", "other.jpg"), "wb").write(blob[:-1] + b"!")   # same size, different
        stats = engine.Stats()
        res = engine.find_duplicates(tmp, g, threading.Event(), min_mb=0.1, stats=stats)
        assert [i.paths[0] for i in res.items] == copies, [i.paths[0] for i in res.items]
        assert stats.found == 400_000 and stats.files == 4, (stats.found, stats.files)
        out = engine.clean(res.items, g, threading.Event(), log=lambda m: None)
        assert out["files"] == 2 and os.path.exists(copies[0]), out          # oldest kept
        assert not os.path.exists(copies[1]) and not os.path.exists(copies[2])

        # a file changed after the scan is skipped
        big = os.path.join(tmp, "video.mp4")
        open(big, "wb").write(b"v" * (2 << 20))
        res = engine.scan_files(tmp, g, threading.Event(), min_mb=1)
        assert [i.paths[0] for i in res.items] == [big]
        open(big, "ab").write(b"more")
        out = engine.clean(res.items, g, threading.Event(), log=lambda m: None)
        assert out["skipped"] == 1 and os.path.exists(big), out
        assert engine.scan_files(tmp, g, threading.Event(), min_mb=1, older_days=30).items == []

    # --- rule table audit: no rule can reach personal files or folders
    personal = ("desktop", "documents", "downloads", "pictures", "videos", "music", "onedrive", "favorites",
                "contacts", "saved games")
    allowed_roots = ("%LOCALAPPDATA%\\", "%APPDATA%\\", "%TEMP%", "%SYSTEMROOT%\\", "%PROGRAMDATA%\\",
                     "%SYSTEMDRIVE%\\NVIDIA\\*", "%SYSTEMDRIVE%\\AMD\\*", "%USERPROFILE%\\.",
                     "%USERPROFILE%\\GO\\PKG\\", "%USERPROFILE%\\ANACONDA3\\PKGS", "%USERPROFILE%\\MINICONDA3\\PKGS",
                     "%USERPROFILE%\\*.HPROF")
    for rule in engine.rules.SYSTEM_RULES:
        assert rule["risk"] in ("safe", "review") and rule["action"] in ("contents", "tree", "files"), rule["id"]
        for t in rule["paths"]:
            up = t.upper()
            assert up.startswith(allowed_roots), f"{rule['id']}: unexpected root {t}"
            assert not any(f"\\{p.upper()}" in up for p in personal), f"{rule['id']}: touches personal folder {t}"
        for prof in engine.user_profiles(False):
            for t in rule["paths"]:
                for p in engine.expand(t, prof):
                    assert g.check(p, is_file=rule["action"] == "files") is None or rule["admin"], (rule["id"], p)
                    parts = {s.lower() for s in engine.norm(p).split("\\")}
                    assert not parts & set(personal), (rule["id"], p)

    deep_dirs = {n.lower() for r in engine.rules.DEEP_RULES if r["action"] == "tree" for n in r["paths"]}
    deep_files = [n.lower() for r in engine.rules.DEEP_RULES if r["action"] == "files" for n in r["paths"]]
    for name in (".git", ".svn", "src", "build", "dist", "bin", "obj", "target", "venv", ".venv", "documents",
                 "photos", "backup", "projects", ".vscode", ".idea", "data", "models", ".ssh", ".gnupg"):
        assert name not in deep_dirs, f"deep scan would delete folders named {name}"
    import fnmatch
    for name in ("report.docx", "budget.xlsx", "slides.pptx", "thesis.pdf", "photo.jpg", "clip.mp4", "notes.txt",
                 "id_rsa", "wallet.dat", "app.db", "save.sav", "backup.zip", "project.psd", "passwords.kdbx",
                 "main.py", "package.json", "readme.md", "desktop.ini", "~notes.txt", "$data.bin"):
        assert not any(fnmatch.fnmatchcase(name, p) for p in deep_files), f"deep scan would delete {name}"
    for rule in engine.rules.DEEP_RULES:
        if rule["id"] in ("dumps", "old_tmp", "mac_meta", "mac_forks", "node_modules"):
            assert rule["risk"] == "review", f"{rule['id']} must never be pre-selected"
    for rule in (engine.RECYCLE_RULE, engine.FILE_RULE, engine.DUP_RULE):
        assert rule["risk"] == "review", f"{rule['id']} must never be pre-selected"

    assert engine.list_drives(), "no drives listed"
    print("all engine checks passed")


if __name__ == "__main__":
    main()
