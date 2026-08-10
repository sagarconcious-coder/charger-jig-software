# PyInstaller spec for Charger Testing JIG (webview edition).
# Build with:  .venv\Scripts\pyinstaller charger_jig.spec
import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "can_jig_busmaster.dbc"), "."),
    (str(ROOT / "EV Battery Charger CAN DBC v1.4.dbc"), "."),
    (str(ROOT / "backend" / "config" / "test_profile.json"), "backend/config"),
    (str(ROOT / "backend" / "config" / "server_config.json"), "backend/config"),
    (str(ROOT / "frontend"), "frontend"),
]

a = Analysis(
    [str(ROOT / "backend" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["cantools.database.can.formats.dbc", "webview.platforms.edgechromium"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ChargerTestingJIG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
