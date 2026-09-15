"""Cleanup rule table. Pure data - edit here to add or remove targets.

Path templates use %ENV% variables and glob wildcards (* only, expanded one
level per segment). Every expanded path is still checked by the guard rails in
engine.py before anything is sized or deleted, so a bad entry here is refused,
never executed.

Fields
    id        unique key
    cat       category shown in the UI
    label     human name
    paths     templates; "system" rules resolve them on the Windows drive only
    action    "contents"  empty the folder, keep the folder
              "tree"      delete the folder itself
              "files"     templates match files, delete each
    risk      "safe"   regenerates on its own, pre-checked
              "review" costs a re-download or may hold data, unchecked
    procs     process names that lock these files; rule is blocked while running
    min_age   hours; files modified more recently are left alone
    admin     needs an elevated process
    note      shown in the UI
"""

SAFE, REVIEW = "safe", "review"


def R(id, cat, label, paths, action="contents", risk=SAFE, procs=(), min_age=0,
      admin=False, note=""):
    return dict(id=id, cat=cat, label=label, paths=list(paths), action=action, risk=risk,
                procs=[p.lower() for p in procs], min_age=min_age, admin=admin, note=note)


_CHROMIUM = ("Cache", "Code Cache", "GPUCache", "DawnWebGPUCache", "DawnGraphiteCache",
             "Service Worker\\CacheStorage", "Service Worker\\ScriptCache")


def _profiles(root):
    # Default and "Profile N" both match "*"; non-profile folders simply lack these subfolders.
    return [f"{root}\\*\\{c}" for c in _CHROMIUM] + [
        f"{root}\\GrShaderCache", f"{root}\\ShaderCache", f"{root}\\GraphiteDawnCache"]


# Rules that only make sense on the drive Windows lives on (current user's profile).
SYSTEM_RULES = [
    # --- Windows ---------------------------------------------------------
    R("win_temp", "Windows", "System temp folder", [r"%SystemRoot%\Temp"], min_age=24, admin=True),
    R("wu_cache", "Windows", "Windows Update download cache",
      [r"%SystemRoot%\SoftwareDistribution\Download"], admin=True, min_age=24,
      note="Windows re-downloads pending updates if needed."),
    R("wer", "Windows", "Windows error reports", [r"%ProgramData%\Microsoft\Windows\WER"], admin=True),
    R("kernel_reports", "Windows", "Kernel crash reports / minidumps",
      [r"%SystemRoot%\LiveKernelReports", r"%SystemRoot%\Minidump"], admin=True),
    R("memory_dmp", "Windows", "Full memory dump", [r"%SystemRoot%\MEMORY.DMP"], action="files", admin=True),
    R("win_logs", "Windows", "Servicing logs (CBS / DISM / WindowsUpdate)",
      [r"%SystemRoot%\Logs\CBS", r"%SystemRoot%\Logs\DISM", r"%SystemRoot%\Logs\WindowsUpdate"],
      admin=True, min_age=24),
    R("prefetch", "Windows", "Prefetch data", [r"%SystemRoot%\Prefetch"], admin=True, risk=REVIEW,
      note="Rebuilds itself; the next few app launches are slightly slower."),

    # --- User temp -------------------------------------------------------
    R("user_temp", "Temp & crash dumps", "Your temp folder", [r"%TEMP%"], min_age=24,
      note="Files touched in the last 24 hours are kept (installers may be using them)."),
    R("crashdumps", "Temp & crash dumps", "App crash dumps", [r"%LOCALAPPDATA%\CrashDumps"]),
    R("shader", "Temp & crash dumps", "DirectX / NVIDIA / AMD shader caches",
      [r"%LOCALAPPDATA%\D3DSCache", r"%LOCALAPPDATA%\NVIDIA\DXCache", r"%LOCALAPPDATA%\NVIDIA\GLCache",
       r"%LOCALAPPDATA%\AMD\DxCache", r"%LOCALAPPDATA%\AMD\DxcCache"]),
    R("hprof", "Temp & crash dumps", "Java heap dumps in your home folder",
      [r"%USERPROFILE%\*.hprof"], action="files"),

    # --- Browsers --------------------------------------------------------
    R("chrome", "Browsers", "Chrome caches (logins, history, bookmarks untouched)",
      _profiles(r"%LOCALAPPDATA%\Google\Chrome\User Data"), procs=["chrome.exe"]),
    R("edge", "Browsers", "Edge caches", _profiles(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
      procs=["msedge.exe"]),
    R("brave", "Browsers", "Brave caches", _profiles(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data"),
      procs=["brave.exe"]),
    R("firefox", "Browsers", "Firefox cache", [r"%LOCALAPPDATA%\Mozilla\Firefox\Profiles\*\cache2"],
      procs=["firefox.exe"]),
    R("opera", "Browsers", "Opera caches",
      [r"%LOCALAPPDATA%\Opera Software\Opera Stable\Cache", r"%LOCALAPPDATA%\Opera Software\Opera GX Stable\Cache"],
      procs=["opera.exe"]),
    R("chrome_ai", "Browsers", "Chrome on-device AI models",
      [r"%LOCALAPPDATA%\Google\Chrome\User Data\OptGuideOnDeviceModel",
       r"%LOCALAPPDATA%\Google\Chrome\User Data\OptGuideOnDeviceClassifierModel",
       r"%LOCALAPPDATA%\Google\Chrome\User Data\optimization_guide_model_store"],
      action="tree", risk=REVIEW, procs=["chrome.exe"],
      note="Turn off chrome://settings/ai first or Chrome downloads them again."),

    # --- Developer caches ------------------------------------------------
    R("npm", "Developer caches", "npm / npx cache",
      [r"%LOCALAPPDATA%\npm-cache\_cacache", r"%LOCALAPPDATA%\npm-cache\_npx", r"%APPDATA%\npm-cache"],
      procs=["node.exe"]),
    R("pip", "Developer caches", "pip / uv caches", [r"%LOCALAPPDATA%\pip\Cache", r"%LOCALAPPDATA%\uv\cache"],
      procs=["uv.exe"]),
    R("yarn", "Developer caches", "Yarn / pnpm / Bun / node-gyp caches",
      [r"%LOCALAPPDATA%\Yarn\Cache", r"%LOCALAPPDATA%\pnpm-cache", r"%LOCALAPPDATA%\pnpm\store",
       r"%USERPROFILE%\.bun\install\cache", r"%LOCALAPPDATA%\node-gyp"], procs=["node.exe", "bun.exe"]),
    R("gradle", "Developer caches", "Gradle caches and daemon logs",
      [r"%USERPROFILE%\.gradle\caches", r"%USERPROFILE%\.gradle\daemon"], procs=["java.exe", "studio64.exe"],
      note="Next build re-downloads dependencies (needs internet)."),
    R("android_tmp", "Developer caches", "Android SDK temp / partial downloads",
      [r"%LOCALAPPDATA%\Android\Sdk\.temp", r"%LOCALAPPDATA%\Android\Sdk\.downloadIntermediates"],
      procs=["studio64.exe"]),
    R("studio_tmp", "Developer caches", "Android Studio tmp and logs",
      [r"%LOCALAPPDATA%\Google\AndroidStudio*\tmp", r"%LOCALAPPDATA%\Google\AndroidStudio*\log"],
      procs=["studio64.exe"]),
    R("maven", "Developer caches", "Maven repository", [r"%USERPROFILE%\.m2\repository"], risk=REVIEW,
      procs=["java.exe"], note="Large re-download on next build. Breaks offline builds until then."),
    R("nuget", "Developer caches", "NuGet packages", [r"%USERPROFILE%\.nuget\packages"], risk=REVIEW,
      procs=["dotnet.exe", "devenv.exe"]),
    R("cargo", "Developer caches", "Rust / Go module caches",
      [r"%USERPROFILE%\.cargo\registry\cache", r"%USERPROFILE%\go\pkg\mod\cache"], risk=REVIEW,
      procs=["cargo.exe", "go.exe"]),
    R("dotcache", "Developer caches", "~/.cache (tool caches, may include AI models)",
      [r"%USERPROFILE%\.cache"], risk=REVIEW,
      note="Can contain downloaded ML models (Hugging Face etc). Check before cleaning."),
    R("playwright", "Developer caches", "Playwright browsers", [r"%LOCALAPPDATA%\ms-playwright"], risk=REVIEW),
    R("build_caches", "Developer caches", "Go build / NuGet HTTP / Electron / Composer caches",
      [r"%LOCALAPPDATA%\go-build", r"%LOCALAPPDATA%\NuGet\v3-cache", r"%LOCALAPPDATA%\NuGet\plugins-cache",
       r"%LOCALAPPDATA%\electron\Cache", r"%LOCALAPPDATA%\electron-builder\Cache", r"%LOCALAPPDATA%\Composer",
       r"%LOCALAPPDATA%\Unity\cache"], procs=["go.exe", "dotnet.exe", "unity.exe"]),
    R("gradle_wrapper", "Developer caches", "Gradle wrapper distributions", [r"%USERPROFILE%\.gradle\wrapper\dists"],
      risk=REVIEW, procs=["java.exe", "studio64.exe"], note="Each project re-downloads its Gradle version."),
    R("conda", "Developer caches", "Conda package cache",
      [r"%USERPROFILE%\.conda\pkgs", r"%USERPROFILE%\anaconda3\pkgs", r"%USERPROFILE%\miniconda3\pkgs"],
      risk=REVIEW, procs=["conda.exe", "python.exe"], note="Same as 'conda clean --all'. Environments are untouched."),
    R("jetbrains", "Developer caches", "JetBrains IDE caches and logs",
      [r"%LOCALAPPDATA%\JetBrains\*\caches", r"%LOCALAPPDATA%\JetBrains\*\log", r"%LOCALAPPDATA%\JetBrains\*\index"],
      risk=REVIEW, procs=["idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe", "clion64.exe",
                          "goland64.exe", "phpstorm64.exe", "datagrip64.exe", "rustrover64.exe"],
      note="Indexes rebuild on next launch; the first start is slow."),
    R("android_images", "Developer caches", "Android emulator system images",
      [r"%LOCALAPPDATA%\Android\Sdk\system-images"], action="tree", risk=REVIEW,
      procs=["studio64.exe", "emulator.exe", "qemu-system-x86_64.exe"],
      note="Emulators using these images stop working until re-downloaded in SDK Manager."),

    # --- Apps --------------------------------------------------------------
    R("vscode", "Apps", "VS Code caches and logs",
      [r"%APPDATA%\Code\Cache", r"%APPDATA%\Code\CachedData", r"%APPDATA%\Code\CachedExtensionVSIXs",
       r"%APPDATA%\Code\logs"], procs=["code.exe"]),
    R("claude", "Apps", "Claude desktop caches and logs",
      [r"%APPDATA%\Claude\Cache", r"%APPDATA%\Claude\Code Cache", r"%APPDATA%\Claude\GPUCache",
       r"%APPDATA%\Claude\DawnGraphiteCache", r"%APPDATA%\Claude\DawnWebGPUCache", r"%APPDATA%\Claude\logs",
       r"%APPDATA%\Claude\Crashpad", r"%APPDATA%\Claude\sentry", r"%APPDATA%\Claude\Service Worker\CacheStorage"],
      procs=["claude.exe"]),
    R("chat_apps", "Apps", "Discord / Slack / Teams caches",
      [r"%APPDATA%\discord\Cache", r"%APPDATA%\discord\Code Cache", r"%APPDATA%\discord\GPUCache",
       r"%APPDATA%\Slack\Cache", r"%APPDATA%\Slack\Service Worker\CacheStorage",
       r"%APPDATA%\Microsoft\Teams\Cache"], procs=["discord.exe", "slack.exe", "teams.exe", "ms-teams.exe"]),
    R("postman", "Apps", "Postman / Zoom caches and logs",
      [r"%APPDATA%\Postman\Cache", r"%APPDATA%\Postman\logs", r"%APPDATA%\Zoom\logs"],
      procs=["postman.exe", "zoom.exe"]),
    R("updaters", "Apps", "Leftover app installers and updater downloads",
      [r"%LOCALAPPDATA%\Downloaded Installations", r"%LOCALAPPDATA%\*-updater\pending"], risk=REVIEW),
    R("teams_new", "Apps", "New Teams cache",
      [r"%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\EBWebView\Default\Cache",
       r"%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\EBWebView\Default\Code Cache"],
      procs=["ms-teams.exe"]),
    R("office_cache", "Apps", "Office document cache", [r"%LOCALAPPDATA%\Microsoft\Office\16.0\OfficeFileCache"],
      risk=REVIEW, procs=["winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe", "onedrive.exe"],
      note="Unsynced OneDrive/SharePoint edits live here. Make sure Office shows everything as saved."),
    R("adobe_media", "Apps", "Adobe media cache",
      [r"%APPDATA%\Adobe\Common\Media Cache Files", r"%APPDATA%\Adobe\Common\Media Cache"],
      procs=["premiere pro.exe", "afterfx.exe", "adobe media encoder.exe", "photoshop.exe"],
      note="Premiere / After Effects rebuild previews; first playback is slower."),
    R("spotify", "Apps", "Spotify offline cache", [r"%LOCALAPPDATA%\Spotify\Storage", r"%LOCALAPPDATA%\Spotify\Data"],
      risk=REVIEW, procs=["spotify.exe"], note="Downloaded playlists need downloading again."),
    R("user_wer", "Temp & crash dumps", "Your Windows error reports",
      [r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive", r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue"]),

    # --- Driver leftovers (machine-wide) ----------------------------------
    R("driver_extract", "Windows", "Extracted driver installers (C:\\NVIDIA, C:\\AMD)",
      [r"%SystemDrive%\NVIDIA\*", r"%SystemDrive%\AMD\*"], action="tree", risk=REVIEW, admin=True,
      note="Unpacked setup files left by driver installers. Installed drivers are not affected."),
    R("nvidia_downloads", "Windows", "NVIDIA driver downloads",
      [r"%ProgramData%\NVIDIA Corporation\Downloader"], admin=True, procs=["nvidia app.exe", "nvcontainer.exe"]),
]


# Found by walking the whole selected drive (any drive, including C:).
# kind "dir" matches folder names, "file" matches file-name globs.
DEEP_RULES = [
    R("pycache", "Found on drive", "__pycache__ folders", ["__pycache__"], action="tree",
      note="Python recreates these automatically."),
    R("dumps", "Found on drive", "Crash / heap dump files (*.dmp, *.hprof)", ["*.dmp", "*.hprof"], action="files"),
    R("thumbs", "Found on drive", "Thumbs.db / .DS_Store", ["Thumbs.db", ".DS_Store"], action="files"),
    R("node_modules", "Found on drive", "node_modules folders (restored by npm install)", ["node_modules"],
      action="tree", risk=REVIEW,
      note="Only folders next to a package.json, outside app installs. Re-run npm install afterwards."),
    R("old_tmp", "Found on drive", "*.tmp files older than 7 days", ["*.tmp"], action="files", risk=REVIEW,
      min_age=24 * 7),
    R("tool_caches", "Found on drive", "Test / lint caches (.pytest_cache, .mypy_cache, .ruff_cache)",
      [".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox"], action="tree",
      note="Recreated on the next test or lint run."),
    R("office_owner", "Found on drive", "Office lock files (~$*.docx etc) older than 1 day",
      ["~$*.doc*", "~$*.xls*", "~$*.ppt*"], action="files", min_age=24,
      note="Left behind when Office closes unexpectedly. Hidden 162-byte files."),
    R("mac_meta", "Found on drive", "macOS metadata (.Spotlight-V100, .Trashes, .fseventsd)",
      [".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems"], action="tree", risk=REVIEW,
      note="Created when the drive was plugged into a Mac. The Mac recreates them if needed."),
    R("mac_forks", "Found on drive", "macOS resource-fork files (._*)", ["._*"], action="files", risk=REVIEW),
]
