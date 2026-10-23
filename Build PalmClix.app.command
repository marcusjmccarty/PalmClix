#!/bin/bash
set -e
cd "$(dirname "$0")"
printf '\nPALMCLIX MAC v1.0 — FINAL LOCAL BUILDER — LOCAL APP BUILDER\n\n'
printf 'This compiles Swift and bundles the USB decoder on this Mac.\n'
printf 'It does NOT connect to the physical camera.\n\n'
./setup_mac.sh
./build_app.sh
printf '\nDone. You can now double-click PalmClix.app and move it to Applications.\n'
open -R "$PWD/PalmClix.app"
