# -*- mode: python ; coding: utf-8 -*-
import shutil
from pathlib import Path
from PIL import Image

# Generate favicon.ico from the source PNG at build time
_png = Path('ui/favicon.png')
_ico = Path('favicon.ico')
if _png.exists():
    img = Image.open(_png)
    img.save(_ico, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])

a = Analysis(
    ['../main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../ui/dist',     'ui/dist'),
        ('CHANGELOG.md', 'helpers'),
        ('../helpers/calibrate.py', 'helpers'),
        ('../favicon.ico', '.'),
        ('version.txt', '.'),
    ],
    hiddenimports=[
        # PySide6 web engine (not auto-detected)
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtNetwork',
        # calibration GUI
        'tkinter',
        'tkinter.font',
        'tkinter.messagebox',
        '_tkinter',
        # screen capture
        'mss',
        'mss.windows',
        # image processing
        'PIL',
        'PIL.Image',
        'PIL.ImageFilter',
        'PIL.ImageTk',
        'PIL.ImageEnhance',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        # OCR wrapper (tesseract binary installed separately)
        'pytesseract',
        # networking
        'requests',
        'urllib3',
        # config
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BDO-Loot-Tracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='../favicon.ico',
    manifest='app.manifest',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BDO-Loot-Tracker',
)

# Place env.example and items/ next to the exe (outside _internal)
_dist = Path('dist') / 'BDO-Loot-Tracker'
shutil.copy('helpers/env.example', str(_dist / '.env'))
_items_dest = _dist / 'items'
if _items_dest.exists():
    shutil.rmtree(_items_dest)
shutil.copytree('items', str(_items_dest))
