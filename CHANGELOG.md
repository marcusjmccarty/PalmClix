# Changelog

## 1.1.0 — Windows version and frameless interface
- **New: PalmClix for Windows** (Python/Tk). Frameless camera-shaped window, right-click menus, Ctrl shortcuts, same USB backend.
- macOS: Import Studio window removed. All its options are now in the menu bar (File, Edit, View, Go, Camera, Window).
- macOS: the window frame is gone. The camera artwork is the window, and you drag its body to move it.
- Download imports directly. Save copies selected photos. The progress bar on the camera fills during transfers.
- Fixed: the Preview button now opens every selected photo explicitly in Preview and reports moved or missing files instead of failing silently.
- Backend: Windows file locking, a bundled libusb-1.0.dll and a fallback for volumes without hard-link support.
- The offline demo asks for a .pcap recording when none is bundled.

## 1.0.0 — Final local-build release
- DSC-matched nonlinear 10-photo color profile; retain v0.4 legacy profile.
- Recovery Lab: catalog diagnostics and opt-in extra-stream forensic probe.
- Connection readiness check and inter-process camera lock.
- Updated GUI controls, logs and manifests, preserving original artwork and working protocol.
- Expanded replay and regression suite for seven- and ten-photo sessions.

## 0.4 RC1
- Import Studio, progress and export options, last-good gallery and safe imports.

## 0.3
- Locally buildable portable macOS .app.

## 0.2.2
- Seven-photo catalog variant after battery power loss.
