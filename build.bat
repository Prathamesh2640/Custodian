@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    py -3.12 -m venv .venv || goto :fail
)
.venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

if not exist src\icon.ico .venv\Scripts\python src\make_icon.py
echo Running guard-rail tests...
.venv\Scripts\python tests\test_engine.py || (echo Tests failed - not building. & goto :fail)

rem --noupx: UPX-packed executables trigger far more antivirus false positives.
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
    --name Custodian --paths src --distpath dist --workpath build --specpath build ^
    --icon "%CD%\src\icon.ico" --add-data "%CD%\src\icon.ico;." ^
    --version-file "%CD%\packaging\version_info.txt" ^
    --exclude-module tkinter src\main.py || goto :fail

echo.
echo Built dist\Custodian.exe
exit /b 0

:fail
echo BUILD FAILED
exit /b 1
