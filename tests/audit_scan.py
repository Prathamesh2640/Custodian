"""Read-only safety audit on real drives. Scans like the app does and checks every path it would clean.

Run:  .venv\\Scripts\\python tests\\audit_scan.py [C:\\ D:\\ ...]
Nothing is deleted. Exits non-zero if any target looks unsafe.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import engine  # noqa: E402
import rules  # noqa: E402

PERSONAL = {"desktop", "documents", "downloads", "pictures", "videos", "music", "onedrive", "favorites",
            "contacts", "saved games"}
DEEP_IDS = {r["id"] for r in rules.DEEP_RULES}
# Names a deep-scan target is allowed to end in (the thing actually being removed)
DEEP_LEAVES = {n.lower() for r in rules.DEEP_RULES if r["action"] == "tree" for n in r["paths"]}


def audit(root):
    problems = []
    guard = engine.Guard(root)
    stats = engine.Stats()
    t = time.monotonic()
    res = engine.scan(root, guard, threading.Event(), deep=True, admin=engine.is_admin(), all_users=True,
                      stats=stats)
    for item in res.items:
        rule = item.rule
        for p in item.paths:
            if rule["action"] == "recyclebin":
                if engine.norm(p) != guard.root:
                    problems.append(f"recycle bin target is not the drive root: {p}")
                continue
            why = guard.check(p, is_file=rule["action"] == "files")
            if why:
                problems.append(f"{rule['id']}: guard refuses {p} ({why})")
            parts = [s.lower() for s in engine.norm(p).split("\\")]
            if rule["id"] not in DEEP_IDS and set(parts) & PERSONAL:
                problems.append(f"{rule['id']}: system rule reaches a personal folder: {p}")
            if rule["action"] == "tree" and rule["id"] in DEEP_IDS and parts[-1] not in DEEP_LEAVES:
                problems.append(f"{rule['id']}: deep target has an unexpected name: {p}")
            if rule["action"] == "files" and rule["id"] in DEEP_IDS:
                name = os.path.basename(p).lower()
                if not any(__import__("fnmatch").fnmatchcase(name, pat.lower()) for pat in rule["paths"]):
                    problems.append(f"{rule['id']}: file does not match its pattern: {p}")
    pre = [i for i in res.items if i.rule["risk"] == rules.SAFE and not i.blocked]
    print(f"\n{root}  scanned {stats.files:,} files in {time.monotonic() - t:.0f}s")
    print(f"  {len(res.items)} items, {engine.fmt_size(sum(i.size for i in res.items))} total; "
          f"pre-selected (safe, unblocked): {len(pre)} items, {engine.fmt_size(sum(i.size for i in pre))}")
    for i in sorted(res.items, key=lambda i: -i.size):
        flag = "pre-selected" if i in pre else ("blocked: " + i.blocked if i.blocked else "unticked (review)")
        print(f"  {engine.fmt_size(i.size):>10}  {i.label[:52]:52}  {flag}")
    for p in problems:
        print("  PROBLEM", p)
    return problems


if __name__ == "__main__":
    roots = sys.argv[1:] or [d.root for d in engine.list_drives() if d.kind == "Local disk"]
    found = [p for r in roots for p in audit(r)]
    print(f"\n{'SAFE: no problems found' if not found else f'{len(found)} PROBLEMS'}  (nothing was deleted)")
    sys.exit(1 if found else 0)
