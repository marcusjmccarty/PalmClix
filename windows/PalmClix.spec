# PyInstaller spec for PalmClix for Windows.
# Builds one folder containing:
#   PalmClix.exe          - the camera-shaped window (no console)
#   palmclix_backend.exe  - the read-only USB/photo helper (console, launched hidden)
# Both share a single _internal folder. libusb-1.0.dll must be placed in
# windows/ before building (build_windows.ps1 downloads it).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "Sources", "PalmClix", "Assets")
LIBUSB = os.path.join(SPECPATH, "libusb-1.0.dll")
ICON = os.path.join(SPECPATH, "PalmClix.ico")

gui = Analysis(
    [os.path.join(SPECPATH, "palmclix_win.py")],
    pathex=[ROOT],
    datas=[(ASSETS, "Assets"), (os.path.join(ROOT, "Artwork", "PalmClix_icon_1024.png"), "Artwork")],
    hiddenimports=["PIL._tkinter_finder"],
    excludes=["cv2", "numpy", "usb"],
)
backend = Analysis(
    [os.path.join(ROOT, "palmclix.py")],
    pathex=[ROOT],
    binaries=[(LIBUSB, ".")],
    hiddenimports=["decode_palmclix", "usb.backend.libusb1"],
    excludes=["tkinter"],
)

gui_pyz = PYZ(gui.pure)
backend_pyz = PYZ(backend.pure)

gui_exe = EXE(
    gui_pyz, gui.scripts, [],
    exclude_binaries=True,
    name="PalmClix",
    console=False,
    icon=ICON if os.path.exists(ICON) else None,
    version=os.path.join(SPECPATH, "version_info.txt"),
)
backend_exe = EXE(
    backend_pyz, backend.scripts, [],
    exclude_binaries=True,
    name="palmclix_backend",
    console=True,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    gui_exe, gui.binaries, gui.datas,
    backend_exe, backend.binaries, backend.datas,
    name="PalmClix",
)
