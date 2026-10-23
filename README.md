# PalmClix

A revival of the 1990s **PalmClix** digital-camera software for **macOS** and **Windows**. Originally the camera only worked with Windows XP. This brings back the original camera-shaped interface, frameless and squiggly as ever, and downloads photos over USB on modern computers.

| | macOS | Windows |
|---|---|---|
| App | Native Swift/AppKit | Python/Tk |
| Options live in | The menu bar (File · Edit · View · Go · Camera · Window) | A right-click menu on the camera (same menus) |
| Requires | macOS 12+, Apple Silicon | Windows 10/11, 64-bit, plus a one-time WinUSB driver install |

Both versions share the same read-only USB and photo-decoding backend (`palmclix.py`).

## Download

Get the latest build from **[Releases](../../releases)**:

- **PalmClix-macOS.zip**: unzip, then move `PalmClix.app` to Applications. The app is ad-hoc signed, not notarized. The first time, right-click it and choose **Open**, or run `xattr -dr com.apple.quarantine /Applications/PalmClix.app`.
- **PalmClix-Windows.zip**: unzip anywhere and run `PalmClix.exe`. SmartScreen may warn about an unrecognized app; choose **More info → Run anyway**.

### Windows: one-time USB driver

libusb needs the generic WinUSB driver bound to the camera:

1. Plug in the camera and run [Zadig](https://zadig.akeo.ie).
2. **Options → List All Devices**, then select the device with USB ID **2770 9120**.
3. Choose **WinUSB** and click **Install / Replace Driver**.

This affects only that camera. To undo it, uninstall the device in Device Manager.

## Using it

| Camera button | Action | Mac | Windows |
|---|---|---|---|
| Download | Import photos from the camera | ⌘D | Ctrl+D |
| Save (floppy) | Copy selected photos to a folder | ⌘S | Ctrl+S |
| Picture | Open selected photos in Preview / your image viewer | ⌘O | Ctrl+O |
| Grid | Select / deselect all | ⌘A | Ctrl+A |
| ◀ ▶ | Previous / next gallery page | ⌘[ ⌘] | Ctrl+[ Ctrl+] |
| – / ✕ / ? | Minimize / quit / about | ⌘M ⌘Q | |

Drag the camera body to move the window. Double-click a thumbnail to open it.
Output format (PNG, JPEG or both), color processing, import folder, camera connection checks and the Recovery Lab are in the **menu bar** on Mac and the **right-click menu** on Windows.

Each import creates `Pictures/PalmClix_<date>_<id>/` containing:

- `Raw/`: original sensor data (PGM), never altered
- `Photos/`: converted PNG/JPEG
- `Protocol/`: catalog report, manifest with SHA-256 hashes, session log

## Supported camera

VID:PID `2770:9120` (SQ905 chipset), model response `09 05 01 19`, uncompressed 640×480 Bayer stills (catalog type `0x56`). Other variants and compressed modes are deliberately unsupported, and unknown catalog entries fail closed. The app never sends erase, firmware or webcam commands. It does use a register-release command found in both successful XP recordings. Back up irreplaceable photos before experimenting.

### Color processing

The default **DSC-matched** profile uses OpenCV VNG demosaicing and a quadratic color model fitted to ten original Windows DSC BMP/raw pairs. In leave-one-photo-out tests it cut mean per-channel error from 16.84 to 8.20 (0–255 scale); see `COLOR_VALIDATION.json`. This is an empirical approximation of the proprietary pipeline. The original v0.4 **Legacy** look is still available, and raw files are kept, so photos can be reconverted later.

### The mysterious eighth photograph

After a power loss, the camera catalog showed eight occupied slots: an unexplained `0x01` record plus seven stills. Windows XP also transferred only seven. The opt-in **Recovery Lab** (Camera menu) performs one bounded extra-stream read after saving the seven verified frames. It is experimental and not a recovery guarantee; see [RECOVERY_LAB.md](RECOVERY_LAB.md).

## Building from source

**macOS** (Homebrew, Python 3, Xcode Command Line Tools):

```bash
./setup_mac.sh
./build_app.sh        # or double-click "Build PalmClix.app.command"
open PalmClix.app
```

**Windows** (Python 3.12 x64 and 7-Zip on PATH):

```powershell
powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
windows\dist\PalmClix\PalmClix.exe
```

**Run the Windows UI from source** on any OS: `pip install -r requirements.txt`, then `python windows/palmclix_win.py`.

GitHub Actions (`.github/workflows/build.yml`) runs the tests and builds both apps on every push. Pushing a `v*` tag publishes a release with both zips.

### Command-line backend

```bash
python palmclix.py --inspect                 # USB descriptors only
python palmclix.py --usb-status              # read configuration, change nothing
python palmclix.py --ready-check             # claim and release the interface, no photo commands
python palmclix.py --download auto --format png --output ~/Pictures/PalmClix_Live --i-accept-experimental-usb
python palmclix.py --simulate capture.pcap --format png --output ./replay   # offline replay of a USB recording
python palmclix.py --forensics tests/fixtures/after_power_loss_catalog.bin
```

### Tests

```bash
python -m unittest discover -s tests
```

Some replay tests use private USB recordings of the author's own photos. Those recordings are not published, so the tests skip themselves. **File → Import Offline Demo** asks for a `.pcap` recording of your own.

## Credits and notices

- The SQ905 protocol and catalog semantics were cross-checked against libgphoto2's independent [sq905 driver](https://github.com/gphoto/libgphoto2/tree/master/camlibs/sq905). No libgphoto2 code is included.
- The Windows build bundles [libusb](https://libusb.info) (LGPL-2.1), unmodified.
- **The camera-interface artwork is from the original PalmClix software and remains the property of its respective owners.** It is included only to preserve the look of this discontinued product. Rights holders who want it removed can open an issue.
- PalmClix is a trademark of its respective owner. This project is not affiliated with or endorsed by the original manufacturer.
