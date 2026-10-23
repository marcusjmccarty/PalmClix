#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
[[ "$(uname -s)" == "Darwin" ]] || { echo 'Setup is intended for macOS.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Install Python 3 first.' >&2; exit 1; }
command -v brew >/dev/null || { echo 'Install Homebrew from https://brew.sh first.' >&2; exit 1; }
brew list --versions libusb >/dev/null 2>&1 || brew install libusb
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
printf '\nReady! For a standalone app, run: ./build_app.sh\n'
