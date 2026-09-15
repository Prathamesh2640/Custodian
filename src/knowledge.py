"""Cleaning knowledge base: every procedure Custodian knows, plus live recommendations.

Action kinds
    page  jump to a Custodian page           {"page": "cleanup" | "files" | "duplicates"}
    open  open a Windows tool or settings    {"target": "ms-settings:..." | "cleanmgr.exe" | folder}
    run   run a command, output goes to Log  {"args": [...], "admin": bool, "confirm": text | None}
          {drive} in args becomes the selected drive ("D:"), {sysdrive} the Windows drive.
Risk: safe | moderate | high
"""
import os

import engine


def page(label, name):
    return dict(kind="page", label=label, page=name)


def open_(label, target):
    return dict(kind="open", label=label, target=target)


def run(label, args, admin=False, confirm=None):
    return dict(kind="run", label=label, args=args, admin=admin, confirm=confirm)


def ps(command):
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]


def K(id, cat, title, impact, risk, summary, steps=(), actions=()):
    return dict(id=id, cat=cat, title=title, impact=impact, risk=risk, summary=summary,
                steps=list(steps), actions=list(actions))


GUIDE = [
    # ----------------------------------------------------------------- quick wins
    K("temp", "Quick wins", "Temporary files", "0.5 - 5 GB", "safe",
      "Windows and apps leave installers, extracted archives and logs in Temp folders. Custodian keeps "
      "anything touched in the last 24 hours so running installers are not broken.",
      ["Close big apps first so fewer files are locked.", "Cleanup page > Scan > keep 'Safe' items ticked > Clean."],
      [page("Scan for junk", "cleanup"), open_("Open my Temp folder", "%TEMP%")]),
    K("recycle", "Quick wins", "Empty the Recycle Bin", "Varies", "safe",
      "Deleted files still use space until the bin is emptied. Each drive has its own bin; USB sticks have none.",
      ["Open the bin and restore anything you still need.", "Cleanup page lists the bin of the selected drive."],
      [open_("Open Recycle Bin", "shell:RecycleBinFolder"), page("Clean it", "cleanup")]),
    K("browsers", "Quick wins", "Browser caches", "0.5 - 4 GB", "safe",
      "Chrome, Edge, Brave, Firefox and Opera cache images and scripts per profile. Clearing the cache keeps "
      "logins, history, bookmarks and passwords.",
      ["Close the browser completely (check the system tray).", "Cleanup page > Browsers."],
      [page("Scan for junk", "cleanup")]),
    K("storage_sense", "Quick wins", "Turn on Storage Sense", "Ongoing", "safe",
      "Windows' own janitor: empties Temp and the Recycle Bin on a schedule and can make OneDrive files "
      "online-only when space runs low.",
      ["Settings > System > Storage > Storage Sense > On.", "Set 'Run Storage Sense' to 'When disk space is low'."],
      [open_("Open Storage Sense", "ms-settings:storagesense")]),
    K("disk_cleanup", "Quick wins", "Disk Cleanup (system files)", "1 - 30 GB", "safe",
      "The classic tool also removes Windows Update leftovers, Windows.old, Delivery Optimization files, "
      "thumbnail cache and old upgrade logs.",
      ["Open Disk Cleanup, pick the drive.", "Click 'Clean up system files' (asks for admin).",
       "Tick the categories you want and press OK."],
      [open_("Open Disk Cleanup", "cleanmgr.exe")]),

    # ----------------------------------------------------------------- windows
    K("winsxs", "Windows system", "Component store cleanup (WinSxS)", "1 - 6 GB", "safe",
      "Superseded Windows components pile up after every update. DISM is the only supported way to remove "
      "them. Never delete anything in C:\\Windows\\WinSxS by hand.",
      ["Analyze first: look for 'Component Store Cleanup Recommended: Yes'.",
       "Run the cleanup (5-20 min). Do not shut down while it runs.",
       "ResetBase frees more but makes currently installed updates permanent (no uninstall)."],
      [run("Analyze", ["dism", "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"], admin=True),
       run("Clean up", ["dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], admin=True,
           confirm="Removes superseded Windows components. Takes 5-20 minutes; do not shut down."),
       run("Clean up + ResetBase", ["dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup", "/ResetBase"],
           admin=True, confirm="PERMANENT: installed updates can no longer be uninstalled.")]),
    K("windows_old", "Windows system", "Previous Windows installation (Windows.old)", "10 - 30 GB", "moderate",
      "Kept for 10 days after a feature update so you can roll back. Removing it gives the space back "
      "but you can no longer go back to the previous version.",
      ["Settings > System > Storage > Temporary files.", "Tick 'Previous Windows installation(s)' > Remove files.",
       "Or Disk Cleanup > Clean up system files."],
      [open_("Open Temporary files", "ms-settings:storagesense"), open_("Open Disk Cleanup", "cleanmgr.exe")]),
    K("hibernation", "Windows system", "Hibernation file (hiberfil.sys)", "40 - 75% of RAM", "moderate",
      "Reserved so the PC can hibernate. 'Reduced' keeps Fast Startup and roughly halves it; 'Off' deletes it "
      "but also disables Fast Startup.",
      ["Desktops that never hibernate: Reduced or Off.", "Laptops that hibernate on low battery: keep Full."],
      [run("Set reduced", ["powercfg", "/h", "/type", "reduced"], admin=True,
           confirm="Hibernate stops working; Fast Startup is kept."),
       run("Turn off", ["powercfg", "/h", "off"], admin=True, confirm="Disables hibernate AND Fast Startup."),
       run("Turn on", ["powercfg", "/h", "on"], admin=True, confirm="Re-creates hiberfil.sys (uses disk space).")]),
    K("pagefile", "Windows system", "Page file (pagefile.sys)", "2 - 16 GB", "moderate",
      "Virtual memory. Moving it to a second internal drive frees the same amount on C:. Keep a small one "
      "(e.g. 2048 MB) on C: so Windows can still write crash dumps.",
      ["Advanced tab > Performance Settings > Advanced > Virtual memory > Change.",
       "Untick 'Automatically manage'. C: = Custom 2048-4096 MB. Other internal drive = System managed.",
       "Set, OK, reboot. Never put the page file on a USB drive."],
      [open_("Open Virtual memory settings", "SystemPropertiesPerformance.exe")]),
    K("restore", "Windows system", "System Restore points and shadow copies", "2 - 20 GB", "moderate",
      "Restore points can take up to the configured maximum of the drive. Capping them keeps protection but "
      "limits the space.",
      ["View usage first.", "Cap at 5% (older points are dropped automatically when the cap is reached).",
       "Deleting the oldest point is irreversible."],
      [run("Show usage", ["vssadmin", "list", "shadowstorage"], admin=True),
       run("Cap at 5%", ["vssadmin", "resize", "shadowstorage", "/for={drive}", "/on={drive}", "/maxsize=5%"],
           admin=True, confirm="Restore points above 5% of the drive are deleted by Windows."),
       run("Delete oldest point", ["vssadmin", "delete", "shadows", "/for={drive}", "/oldest", "/quiet"],
           admin=True, confirm="PERMANENT: the oldest restore point is removed."),
       open_("Open System Protection", "SystemPropertiesProtection.exe")]),
    K("delivery", "Windows system", "Delivery Optimization cache", "0.5 - 10 GB", "safe",
      "Windows keeps update pieces to share with other PCs. The cache is safe to clear.",
      ["Clear it, then optionally turn off 'Allow downloads from other PCs'."],
      [run("Clear cache", ps("Delete-DeliveryOptimizationCache -Force"), admin=True,
           confirm="Deletes the Delivery Optimization cache."),
       open_("Open Delivery Optimization", "ms-settings:delivery-optimization")]),
    K("update_cache", "Windows system", "Windows Update download cache", "0.2 - 5 GB", "safe",
      "SoftwareDistribution\\Download holds downloaded update packages. Clearing it also fixes some stuck updates.",
      ["Restart as administrator.", "Cleanup page > Windows > Windows Update download cache."],
      [page("Scan for junk", "cleanup"), open_("Open Windows Update", "ms-settings:windowsupdate")]),
    K("compactos", "Windows system", "Compact OS", "2 - 4 GB", "moderate",
      "Compresses Windows system files. Tiny CPU cost on reads; worth it on small SSDs, pointless on large ones.",
      ["Query first. Compacting takes 10-20 minutes."],
      [run("Query state", ["compact", "/CompactOS:query"], admin=True),
       run("Compress Windows", ["compact", "/CompactOS:always"], admin=True,
           confirm="Compresses Windows files. Takes 10-20 minutes."),
       run("Undo", ["compact", "/CompactOS:never"], admin=True, confirm="Decompresses Windows files.")]),
    K("reserved", "Windows system", "Reserved storage", "About 7 GB", "high",
      "Windows reserves space so updates always have room. Disabling it frees the space but updates can fail "
      "when the disk is full. Cannot be changed while an update is pending.",
      ["Check the state. Only disable on small drives that you keep an eye on."],
      [run("Show state", ["dism", "/Online", "/Get-ReservedStorageState"], admin=True),
       run("Disable", ["dism", "/Online", "/Set-ReservedStorageState", "/State:Disabled"], admin=True,
           confirm="Updates may fail when the drive is nearly full."),
       run("Enable", ["dism", "/Online", "/Set-ReservedStorageState", "/State:Enabled"], admin=True,
           confirm="Windows reserves about 7 GB again.")]),
    K("dumps", "Windows system", "Crash dumps and error reports", "0.1 - 30 GB", "safe",
      "MEMORY.DMP, minidumps, LiveKernelReports and WER queues are only needed while diagnosing a crash.",
      ["Cleanup page > Windows / Temp & crash dumps.", "Whole-drive search also finds *.dmp and *.hprof files."],
      [page("Scan for junk", "cleanup")]),
    K("optimize", "Windows system", "Optimize drives (TRIM / defragment)", "Speed", "safe",
      "Not a space saver, but run it after a big cleanup: SSDs get TRIM so freed blocks are reclaimed, "
      "hard disks get defragmented.",
      [], [run("Optimize selected drive", ["defrag", "{drive}", "/O"], admin=True,
               confirm="Optimizes the selected drive. May take a while on hard disks."),
           open_("Open Optimize Drives", "dfrgui.exe")]),
    K("chkdsk", "Windows system", "Check drive for errors", "Health", "safe",
      "Online scan for file system errors. Fix what it reports before a large cleanup on an old drive.",
      [], [run("Scan selected drive", ["chkdsk", "{drive}", "/scan"], admin=True,
               confirm="Runs an online file system scan (read-only unless errors are found).")]),
    K("search_index", "Windows system", "Search index", "0.2 - 5 GB", "moderate",
      "The Windows Search database can bloat. Rebuilding it frees space; search is incomplete while it rebuilds.",
      ["Indexing Options > Advanced > Rebuild.", "Exclude large folders (source trees, VMs) under Modify."],
      [open_("Open Indexing Options", "control.exe srchadmin.dll")]),
    K("never", "Windows system", "Never delete these by hand", "-", "high",
      "C:\\Windows\\WinSxS, C:\\Windows\\Installer, System32\\DriverStore, System Volume Information, "
      "pagefile.sys and hiberfil.sys. Manual deletion breaks updates, uninstallers or boot. Use the "
      "procedures above instead. Custodian refuses to touch them.", [], []),

    # ----------------------------------------------------------------- apps & files
    K("uninstall", "Apps & files", "Uninstall unused apps and duplicate runtimes", "1 - 50 GB", "moderate",
      "Games, trial software and multiple JDK / Python / Node / .NET versions add up fast.",
      ["Settings > Apps > Installed apps > sort by size.", "Keep the runtimes your projects pin, remove the rest.",
       "Leave Edge WebView2 Runtime and Visual C++ Redistributables installed."],
      [open_("Open Installed apps", "ms-settings:appsfeatures"), open_("Classic Programs and Features", "appwiz.cpl")]),
    K("large_old", "Apps & files", "Large and forgotten files", "Varies", "moderate",
      "Videos, ISOs, archives and old installers in Downloads are usually the biggest personal space users.",
      ["Large & old files page: set a size and 'not modified for' filter.", "Prefer Recycle Bin mode."],
      [page("Find large files", "files")]),
    K("duplicates", "Apps & files", "Duplicate files", "Varies", "moderate",
      "Identical photos, videos and downloads saved twice. Custodian compares full content, not names, and "
      "always keeps at least one copy.",
      [], [page("Find duplicates", "duplicates")]),
    K("move_folders", "Apps & files", "Move Downloads / Documents / Desktop to another drive", "Varies", "safe",
      "Moving the known folders keeps C: small permanently. Windows moves the files and updates every shortcut.",
      ["Right-click Downloads > Properties > Location > Move... > pick a folder on D:.",
       "Settings > Storage > Advanced > Where new content is saved: set apps and media to D:."],
      [open_("Open save locations", "ms-settings:savelocations"), open_("Open user folder", "%USERPROFILE%")]),
    K("onedrive", "Apps & files", "OneDrive Files On-Demand", "Varies", "safe",
      "Synced files can live only in the cloud and download when opened.",
      ["Right-click the OneDrive folder > Free up space.", "Or Storage Sense > make content online-only after N days."],
      [open_("Open OneDrive folder", "%OneDrive%")]),
    K("games", "Apps & files", "Game libraries", "10 - 200 GB", "safe",
      "Launchers can move installed games to another drive without re-downloading.",
      ["Steam: Settings > Storage > add D:, then Move install folder.",
       "Xbox app: Manage > Files > Move.", "Epic: uninstall and install to D: (no move feature)."], []),
    K("site_data", "Apps & files", "Browser site data (IndexedDB, offline web apps)", "0.5 - 5 GB", "moderate",
      "Web apps like Clipchamp, Figma or Teams web store offline data that is not cache. Clearing loses "
      "unsynced work for that site only.",
      ["Chrome/Edge: Settings > Privacy > Site settings > View permissions and data stored across sites.",
       "Sort by data stored, delete sites you no longer use."], []),
    K("outlook", "Apps & files", "Outlook offline mailbox (OST)", "1 - 50 GB", "safe",
      "Outlook keeps a local copy of your mailbox. Keeping less offline shrinks it; mail stays on the server.",
      ["File > Account Settings > Account Settings > Change > 'Mail to keep offline' = 1 year or less."], []),

    # ----------------------------------------------------------------- developers
    K("pkg_caches", "Developers", "Package manager caches", "1 - 20 GB", "safe",
      "Every package manager keeps a download cache. The official clean commands are the safest way. "
      "Commands for tools you have not installed simply report an error in the Log.",
      ["Or use Cleanup page > Developer caches, which removes the same folders directly."],
      [run("npm cache clean", ["cmd", "/c", "npm cache clean --force"], confirm="Clears the npm cache."),
       run("pip cache purge", ["cmd", "/c", "pip cache purge"], confirm="Clears the pip cache."),
       run("uv cache clean", ["cmd", "/c", "uv cache clean"], confirm="Clears the uv cache."),
       run("pnpm store prune", ["cmd", "/c", "pnpm store prune"], confirm="Removes unreferenced pnpm packages."),
       run("yarn cache clean", ["cmd", "/c", "yarn cache clean"], confirm="Clears the Yarn cache."),
       run("NuGet locals clear", ["cmd", "/c", "dotnet nuget locals all --clear"], confirm="Clears NuGet caches."),
       run("go clean -modcache", ["cmd", "/c", "go clean -modcache"], confirm="Clears the Go module cache."),
       run("conda clean --all", ["cmd", "/c", "conda clean --all -y"], confirm="Clears conda package caches."),
       run("Stop Gradle daemons", ["cmd", "/c", "gradle --stop"])]),
    K("node_modules", "Developers", "node_modules and build outputs", "1 - 50 GB", "safe",
      "Old projects keep hundreds of MB of dependencies. Custodian finds node_modules next to a package.json "
      "and test/lint caches. For bin/obj/target/dist use 'git clean -xdn' inside a repo to preview.",
      ["Cleanup page with 'Search the whole drive' on.", "Run npm install when you return to a project."],
      [page("Scan for junk", "cleanup")]),
    K("docker", "Developers", "Docker images, containers and build cache", "2 - 100 GB", "moderate",
      "Docker Desktop stores everything in one virtual disk that only grows.",
      ["docker system df shows usage.", "Prune removes stopped containers, unused networks, dangling images "
       "and build cache.", "Then compact the WSL disk (next card) to give the space back to Windows."],
      [run("docker system df", ["docker", "system", "df"]),
       run("docker system prune", ["docker", "system", "prune", "-f"],
           confirm="Removes stopped containers, unused networks, dangling images and build cache."),
       run("docker builder prune", ["docker", "builder", "prune", "-f"], confirm="Removes Docker build cache.")]),
    K("wsl", "Developers", "Compact WSL / Docker virtual disks (.vhdx)", "5 - 100 GB", "moderate",
      "ext4.vhdx files never shrink on their own after you delete files inside Linux.",
      ["Delete what you do not need inside the distro first.", "Shut down WSL (button).",
       "Newer WSL: wsl --manage <distro> --set-sparse true.",
       "Or diskpart: select vdisk file=\"...\\ext4.vhdx\" > attach vdisk readonly > compact vdisk > detach vdisk."],
      [run("List distros", ["wsl", "--list", "--verbose"]),
       run("Shut down WSL", ["wsl", "--shutdown"], confirm="Stops every running WSL distro and Docker Desktop's engine."),
       open_("Open WSL packages folder", "%LOCALAPPDATA%\\Packages")]),
    K("android", "Developers", "Android SDK, emulators and Gradle", "5 - 40 GB", "moderate",
      "System images (1-3 GB each), unused AVDs, old Android Studio version folders and Gradle caches.",
      ["Android Studio > Device Manager: delete emulators you do not use.",
       "SDK Manager: uninstall old platforms and system images.", "Cleanup page > Developer caches."],
      [page("Scan for junk", "cleanup"), open_("Open Android SDK folder", "%LOCALAPPDATA%\\Android\\Sdk")]),
    K("models", "Developers", "AI models (Ollama, Hugging Face, LM Studio)", "5 - 200 GB", "moderate",
      "Local model files are huge. Remove models you no longer run with the tool's own command.",
      ["ollama list, then ollama rm <model>.", "huggingface-cli delete-cache (interactive, run in a terminal).",
       "LM Studio: My Models > delete."],
      [run("ollama list", ["ollama", "list"]), open_("Open ~/.cache", "%USERPROFILE%\\.cache")]),
    K("ide", "Developers", "IDE caches", "0.5 - 10 GB", "safe",
      "VS Code, JetBrains and Android Studio caches and indexes rebuild themselves.",
      ["JetBrains: File > Invalidate Caches also works.", "Cleanup page > Developer caches / Apps."],
      [page("Scan for junk", "cleanup")]),

    # ----------------------------------------------------------------- drives
    K("usb", "Removable & other drives", "USB sticks and SD cards", "Varies", "moderate",
      "Removable drives have no Recycle Bin: every deletion is permanent. Macs leave .Spotlight-V100, "
      ".Trashes and ._ files behind.",
      ["Pick the drive, Cleanup page with whole-drive search on.", "Use Permanent mode (Recycle Bin is refused)."],
      [page("Scan for junk", "cleanup")]),
    K("second_drive", "Removable & other drives", "Use the second drive", "Varies", "safe",
      "Installing apps, games and projects on D: keeps the Windows drive fast and roomy.",
      ["Settings > Storage > Advanced storage settings > Where new content is saved."],
      [open_("Open save locations", "ms-settings:savelocations")]),
]


def recommendations(drives, admin):
    """Cheap checks against this machine. Returns [(level, title, detail, action)]; level: critical|warn|info|good."""
    out = []
    sysroot = engine.system_root()
    for d in drives:
        pct = d.free / d.total * 100 if d.total else 100
        if d.kind != "Removable" and pct < 10:
            out.append(("critical", f"{d.root[:2]} is almost full ({pct:.0f}% free)",
                        f"Only {engine.fmt_size(d.free)} left. Windows slows down and updates fail below 10%.",
                        page("Scan this drive", "cleanup")))
        elif d.kind != "Removable" and pct < 20:
            out.append(("warn", f"{d.root[:2]} is getting full ({pct:.0f}% free)",
                        f"{engine.fmt_size(d.free)} free. Aim for at least 20% free space.",
                        page("Scan this drive", "cleanup")))

    hib = engine.system_file_size("hiberfil.sys")
    if hib > 2 << 30:
        out.append(("warn", f"Hibernation file uses {engine.fmt_size(hib)}",
                    "Set it to 'reduced' to free about half and keep Fast Startup.",
                    dict(GUIDE_BY_ID["hibernation"]["actions"][0], guide="hibernation")))

    pagefile = engine.system_file_size("pagefile.sys")
    others = [d for d in drives if d.kind == "Local disk" and d.root.lower() != sysroot.lower() and d.free > 50 << 30]
    if pagefile > 4 << 30 and others:
        out.append(("info", f"Page file uses {engine.fmt_size(pagefile)} on {sysroot[:2]}",
                    f"{others[0].root[:2]} has {engine.fmt_size(others[0].free)} free. Moving most of it there "
                    "frees the same amount on the Windows drive.", open_("Virtual memory", "SystemPropertiesPerformance.exe")))

    bin_total = sum(engine.recycle_bin_size(d.root)[0] for d in drives)
    if bin_total > 1 << 30:
        out.append(("info", f"Recycle Bins hold {engine.fmt_size(bin_total)}",
                    "Deleted files still use space until the bin is emptied.", page("Empty it", "cleanup")))

    if os.path.isdir(os.path.join(sysroot, "Windows.old")):
        out.append(("warn", "Previous Windows installation found (Windows.old)",
                    "Usually 10-30 GB. Remove it once the current Windows version works well.",
                    open_("Open Disk Cleanup", "cleanmgr.exe")))

    downloads = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
    size = _quick_size(downloads, limit=200_000)
    if size > 5 << 30:
        out.append(("info", f"Downloads folder holds {engine.fmt_size(size)}",
                    "Old installers and videos pile up here. Review large and old files or move the folder.",
                    page("Find large files", "files")))

    model = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data", "OptGuideOnDeviceModel")
    size = _quick_size(model, limit=5000)
    if size > 1 << 30:
        out.append(("info", f"Chrome's on-device AI model uses {engine.fmt_size(size)}",
                    "Turn off chrome://settings/ai, then remove it on the Cleanup page (Review item).",
                    page("Scan for junk", "cleanup")))

    for vhd in _vhdx_files():
        out.append(("info", f"Virtual disk {os.path.basename(vhd[1])} is {engine.fmt_size(vhd[0])}",
                    f"{vhd[1]}. Compact it after deleting data inside WSL/Docker.", page("How to compact", "guide:wsl")))

    if not admin:
        out.append(("info", "Standard mode", "Restart as administrator to clean Windows folders, all accounts, "
                    "and run system procedures.", dict(kind="elevate", label="Restart as administrator")))
    if not [o for o in out if o[0] in ("critical", "warn")]:
        out.insert(0, ("good", "Looking healthy", "No drive is low on space and no big system item needs attention.",
                       None))
    return out


def _quick_size(path, limit):
    """Size of a folder, giving up after `limit` files so the dashboard stays responsive."""
    total = n = 0
    try:
        for _, kind, st in engine.walk(path):
            if kind == "file":
                total += st.st_size
                n += 1
                if n >= limit:
                    break
    except OSError:
        pass
    return total


def _vhdx_files():
    found = []
    for root in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Docker", "wsl")):
        if not os.path.isdir(root):
            continue
        for p, kind, st in engine.walk(root):
            if kind == "file" and p.lower().endswith(".vhdx") and st.st_size > 10 << 30:
                found.append((st.st_size, engine.unlp(p)))
    return sorted(found, reverse=True)[:3]


GUIDE_BY_ID = {g["id"]: g for g in GUIDE}
CATEGORIES = list(dict.fromkeys(g["cat"] for g in GUIDE))
