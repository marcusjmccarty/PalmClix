#!/usr/bin/env python3
"""Offline regression against a successful seven-photo XP USBPcap capture.

Supply YOUR capture file; we deliberately do not redistribute its embedded photos.
"""
import argparse
import pathlib
import tempfile
from palmclix import RecordedDevice, transfer

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('capture',type=pathlib.Path)
a=p.parse_args()
with tempfile.TemporaryDirectory(prefix='palmclix-7photo-replay-') as td:
    device=RecordedDevice(a.capture)
    count=transfer(device, 'auto', pathlib.Path(td)/'out', fmt='none')
    device.finished()
    assert count==7, f'Expected 7 photos, observed {count}'
    files=list((pathlib.Path(td)/'out').glob('PalmClix_*.pgm'))
    assert len(files)==7
    print(f'PASS: {count} photos; initial read marker 0x{device.catalog_marker:02x}; '
          'all USB requests/replies matched; images preserved during offline test.')
