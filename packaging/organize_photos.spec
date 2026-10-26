# PyInstaller spec for Organize photos.app (macOS, Apple Silicon).
# Build:  pyinstaller --noconfirm --clean packaging/organize_photos.spec
#
# --onedir + windowed (console=False) + BUNDLE, as PyInstaller recommends for
# macOS apps. A spec file (rather than CLI flags) is needed to add Info.plist keys.
import os
import re

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
with open(os.path.join(ROOT, "photo_organizer", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)

datas, binaries, hiddenimports = [], [], ["pillow_heif"]
d, b, h = collect_all("pillow_heif")  # includes libheif's dylibs
datas += d
binaries += b
hiddenimports += h
datas += collect_data_files("tzdata")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Organize photos",
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,  # PyInstaller ad-hoc signs, which Apple Silicon requires
)
coll = COLLECT(exe, a.binaries, a.datas, name="Organize photos")
app = BUNDLE(
    coll,
    name="Organize photos.app",
    bundle_identifier="com.mikkel.organizephotos",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "Organize photos",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        # Text for the "access files on a removable volume" prompt.
        "NSRemovableVolumesUsageDescription": "Organize photos sorts the photos on your photo drive.",
    },
)
