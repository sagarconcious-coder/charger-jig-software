# Builds the standalone Windows executable for distribution.
# Run from the project root: .\build_exe.ps1
# Output: dist\ChargerTestingJIG.exe (single file, no Python required to run it)

.\.venv\Scripts\python.exe -m pip install -q pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller charger_jig.spec --noconfirm

Write-Output ""
Write-Output "Build complete: dist\ChargerTestingJIG.exe"
