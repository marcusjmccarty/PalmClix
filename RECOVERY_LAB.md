# Recovery Lab: searching for the eighth photograph

## What we can establish

After battery reset, PalmClix indicated `18/26`. The saved allocation catalog contains eight occupied 16-byte records, with the first marker `0x01` and the next seven `0x56`. Its first address-like range is `0x0A8000`–`0x13AFFF`. The following record is `0x56`, and record nine begins with `0x00` (end marker).

The Windows XP `troubleshoot.pcap` records only seven 307,200-byte image streams. **No eighth image is available to reconstruct offline from this recording.** We cannot establish whether the anomalous record is deleted, invalid, hidden, or otherwise inaccessible.

Offline report (zero camera interaction):

```bash
source .venv/bin/activate
python palmclix.py --forensics tests/fixtures/after_power_loss_catalog.bin
```

## Advanced extra-stream probe (physically untested)

**Warning:** This deliberately goes beyond the proven seven-image transfer sequence. The camera may stall, time out, require reconnecting or lose access to the current session. Do not run with irreplaceable photographs. Back up through Windows XP first. Do not repeat the probe after timeout. It does not erase memory or attempt writes, but a read command beyond a proprietary device's normal stream still has unknown effects.

**GUI:** File → Recovery Lab: Experimental Extra Frame… → explicitly enable once → Import from Camera. This opt-in applies only to the next live import and is never the default.

**Terminal alternative:**

```bash
python palmclix.py --download auto --format png \
  --output "$HOME/Pictures/PalmClix_SingleRecoveryTest" \
  --i-accept-experimental-usb \
  --probe-extra-frame --i-accept-experimental-probe --verbose
```

The program saves the seven recognized raw photographs first. It then attempts to read at most one additional 307,200-byte stream via the already observed bulk-read command type, with a 2.5-second timeout per USB chunk. It cannot seek directly to catalog slot 1. All results are reported in `Recovery/probe_report.json`; a full, nontrivial and non-identical stream (if returned) is saved in `Recovery/EXPERIMENTAL_extra_stream.pgm`. **This is an unverified candidate, not proof of recovery.** Nothing is automatically shown as a trusted eighth photo.

If a candidate is saved, you can view it offline without reconnecting the camera:

```bash
python -c 'from pathlib import Path; from PIL import Image; from decode_palmclix import convert_raw; p=Path.home()/"Pictures/PalmClix_SingleRecoveryTest/Recovery/EXPERIMENTAL_extra_stream.pgm"; Image.fromarray(convert_raw(p), "RGB").save(p.with_suffix(".png"))'
```

We explicitly do **not** change catalog marker `0x01` to `0x56`, modify the camera's memory map, attempt destructive camera commands, or claim that a hypothetical extra stream necessarily belongs to the unknown slot.
