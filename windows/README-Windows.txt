PalmClix for Windows 1.1.0
==========================

The original 1990s PalmClix camera interface, rebuilt for modern Windows
(Windows 10 and 11, 64-bit).

START
  Double-click PalmClix.exe. Keep palmclix_backend.exe and the _internal
  folder next to it.
  Windows SmartScreen may warn that the app is unrecognized because it is not
  code-signed. Choose "More info" > "Run anyway".

ONE-TIME USB DRIVER SETUP
  Windows needs a generic USB driver before PalmClix can talk to the camera.
  1. Plug in the camera.
  2. Download Zadig from https://zadig.akeo.ie and run it.
  3. Options > List All Devices, then pick the device with USB ID 2770 9120.
  4. Choose "WinUSB" and click Install / Replace Driver.
  This replaces the original XP driver for that camera only. To undo it,
  uninstall the device in Device Manager.

USING IT
  Download button (Ctrl+D)  Import photos from the camera
  Save button (Ctrl+S)      Copy selected photos to a folder
  Picture button (Ctrl+O)   Open selected photos in your image viewer
  Grid button (Ctrl+A)      Select / deselect all
  Arrows (Ctrl+[ / Ctrl+])  Previous / next page
  - / X buttons             Minimize / quit
  Drag the camera body to move it.

  RIGHT-CLICK anywhere on the camera for every other option:
  File, Edit, View (output format, color processing), Go, Camera
  (connection check, USB verify, Recovery Lab, driver help) and Window.

  Imports are saved to Pictures\PalmClix_<date>_<id> by default:
    Raw\       original sensor data (never altered)
    Photos\    converted PNG / JPEG
    Protocol\  catalog, manifest, hashes and session log

Back up irreplaceable photos first. The camera protocol was reverse
engineered from Windows XP USB recordings; no erase command is ever sent.
