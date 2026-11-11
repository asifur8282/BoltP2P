# -*- mode: python ; coding: utf-8 -*-
"""
BoltP2P Desktop Daemon - PyInstaller Specification File
Compiles the Python daemon into a standalone, windowless, optimized Windows 11 executable.
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect dynamic submodules
zeroconf_submodules = collect_submodules('zeroconf')
pystray_submodules = collect_submodules('pystray')
winrt_submodules = collect_submodules('winrt')

hidden_imports = list(set([
    'zeroconf',
    'pystray',
    'win11toast',
    'winrt',
    'winrt.windows.ui.notifications',
    'winrt.windows.data.xml.dom',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.storage',
    'winrt.windows.storage.streams',
    'cryptography',
    'cryptography.hazmat.backends.openssl',
    'pyperclip',
    'qrcode',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL.ImageDraw',
    'PIL.ImageGrab',
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
] + zeroconf_submodules + pystray_submodules + winrt_submodules))

# Bulky non-essential scientific/notebook libraries to exclude for minimal binary footprint
bulky_excludes = [
    'matplotlib',
    'pandas',
    'scipy',
    'cv2',
    'IPython',
    'ipykernel',
    'jupyter',
    'jupyterlab',
    'notebook',
    'tornado',
    'sqlalchemy',
    'google',
    'google.cloud',
    'googleapiclient',
    'grpc',
    'openpyxl',
    'fastapi',
    'uvicorn',
    'watchdog',
    'pydantic',
    'pytest',
    'unittest',
]

datas = [
    ('config.json', '.'),
    ('assets', 'assets'),
    ('Downloads/.gitkeep', 'Downloads'),
]

icon_path = os.path.join('assets', 'app_icon.ico')
if not os.path.exists(icon_path):
    icon_path = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=bulky_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='JiffBoltP2P',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowless/Headless tray mode (--noconsole)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
