#!/usr/bin/env python3
"""PalmClix SQ905 USB downloader, release 1.0 (read-only import).

The exact ten-image USB sequence has been confirmed on physical Apple Silicon
hardware by the camera owner. Photo counts are read from the 16-byte entries in
the 0x4000-byte SQ905 allocation catalog, independently documented in libgphoto2.
Only uncompressed 640x480 stills (type 0x56) are decoded. A leading 0x01
placeholder followed by 0x56 entries is supported based on the October 18
XP capture, which transferred exactly seven images for eight catalog slots.
All other unknown formats fail closed. This program includes the camera's recorded register-clear
command (0xa0) but no explicit delete-images, firmware, or webcam action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import contextlib
try:
    import fcntl  # macOS / Linux
except ImportError:  # Windows
    fcntl = None
    import msvcrt
import statistics
import os
import pathlib
import struct
import sys
import tempfile
from datetime import datetime, timezone

VID, PID, ENDPOINT = 0x2770, 0x9120, 0x81
WIDTH, HEIGHT = 640, 480
FRAME_SIZE = WIDTH * HEIGHT
STATUS_BYTE = b'\x50'
REFERENCE_HEADER = bytes.fromhex('09 05 01 19')  # SQ905 model ID, NOT photo count!
MAX_PHOTOS = 64  # conservative program limit; camera capacity is not established
CATALOG_BYTES = 0x4000
CATALOG_ENTRY_BYTES = 16
SUPPORTED_STILL_TYPES = {0x56: (640, 480, 1)}  # documented SQ905 format 0x56
RECORD = struct.Struct('<IIII')
USB_HEADER = struct.Struct('<HQIHBHHBBI')


class ProtocolError(RuntimeError):
    pass


def model_information(header: bytes) -> dict:
    """The four ID bytes identify the device model (not the photo count)."""
    if len(header) != 4:
        raise ProtocolError(f'Expected 4-byte model identifier, got {len(header)} bytes')
    if header != REFERENCE_HEADER:
        raise ProtocolError(f'Unknown camera model ID {header.hex(" ")}; this tested '
                            'protocol variant expects 09 05 01 19. Aborting.')
    return {'model_id': header.hex(' '), 'known': True}


def parse_catalog(data: bytes) -> list[dict]:
    """Return confirmed 0x56 stills, excluding one proven leading 0x01 slot.

    A post-power-loss XP session contained 0x01, seven 0x56 entries, then 0x00;
    the original Windows DSC software fetched exactly seven 640x480 photographs.
    We do not assert what 0x01 *means* in firmware. We accept it only at
    catalog slot 1 and only with the exact known 640x480 allocation bounds.
    All other unknown markers continue to stop before any image-stream read.
    """
    if len(data) != CATALOG_BYTES:
        raise ProtocolError(f'Allocation table must be {CATALOG_BYTES} bytes, got {len(data)}')
    entries = []
    skipped_slot = False
    for offset in range(0, CATALOG_BYTES, CATALOG_ENTRY_BYTES):
        record = data[offset:offset + CATALOG_ENTRY_BYTES]
        slot = offset // CATALOG_ENTRY_BYTES + 1
        code = record[0]
        if code == 0:
            if skipped_slot and not entries:
                raise ProtocolError('Only a 0x01 catalog slot was found; no supported '
                                    'photographs. Stopped before image DATA transfer.')
            return entries
        if code == 0x01 and slot == 1 and record[1:9] == bytes.fromhex('0a800013afff0000'):
            skipped_slot = True
            continue
        if code not in SUPPORTED_STILL_TYPES:
            raise ProtocolError(f'Catalog slot {slot}: unsupported SQ905 '
                                f'image/clip marker 0x{code:02x}. No image-stream '
                                'commands sent. Preserve original photographs '
                                'and use Windows DSC for this session.')
        if len(entries) >= MAX_PHOTOS:
            raise ProtocolError(f'Catalog contains more than {MAX_PHOTOS} photographs; '
                                'this safety limit prevents oversized reads.')
        width, height, ratio = SUPPORTED_STILL_TYPES[code]
        entries.append({'index': len(entries)+1, 'catalog_slot': slot,
                        'type': f'{code:02x}', 'width': width,
                        'height': height, 'byte_count': width*height//ratio})
    raise ProtocolError('No zero terminator found in 16 KB allocation table; aborting')


def event(name: str, data: dict, json_progress=False):
    if json_progress:
        print('PALMCLIX_EVENT ' + json.dumps({'event': name, **data}, sort_keys=True), flush=True)
    elif name in ('metadata', 'photo', 'done'):
        print(f'{name.upper()}: ' + ' '.join(f'{k}={v}' for k, v in data.items()), flush=True)


def ctrl_out(dev, value: int, index: int, byte: int, verbose=False):
    if verbose:
        print(f'CTRL OUT 40:0c value={value:04x} index={index:04x} payload={byte:02x}', file=sys.stderr, flush=True)
    n = dev.ctrl_transfer(0x40, 0x0c, value, index, bytes([byte]), timeout=5000)
    if n != 1:
        raise ProtocolError(f'Control OUT sent {n} of 1 expected bytes')


def ctrl_in(dev, size: int, verbose=False) -> bytes:
    response = bytes(dev.ctrl_transfer(0xc0, 0x0c, 7, 0, size, timeout=5000))
    if verbose:
        print(f'CTRL IN c0:0c value=0007 index=0000: {response.hex()}', file=sys.stderr, flush=True)
    if len(response) != size:
        raise ProtocolError(f'Short control IN: got {len(response)}, expected {size}')
    return response


def expect_status(dev, verbose=False):
    status = ctrl_in(dev, 1, verbose)
    if status != STATUS_BYTE:
        raise ProtocolError(f'Unexpected status {status.hex()}, expected 50')


def read_chunk(dev, size: int, marker: int, verbose=False, timeout=12000) -> bytes:
    ctrl_out(dev, 3, size, marker, verbose)
    data = bytes(dev.read(ENDPOINT, size, timeout=timeout))
    if len(data) != size:
        raise ProtocolError(f'Short bulk read: got {len(data)} bytes, expected {size}')
    return data


def save_bytes_safely(path: pathlib.Path, data: bytes):
    # Use exclusive creation: never overwrite an existing photo (even after a partial run).
    with path.open('xb') as f:
        f.write(data)


def save_image_atomically(image, path: pathlib.Path, encoder: str):
    """Write an image completely, then publish it without silently overwriting files.

    This is intentionally after USB commands finish. A failed decoder leaves
    the original sensor PGM safe in Raw/, with no half-written final PNG/JPEG.
    """
    if path.exists():
        raise ProtocolError(f'Output file already exists: {path}')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.palmclix-', suffix='.' + path.suffix.lstrip('.'),
                                         dir=path.parent, delete=False) as handle:
            temporary = pathlib.Path(handle.name)
        if encoder == 'PNG':
            image.save(temporary, format='PNG')
        else:
            image.save(temporary, format='JPEG', quality=95, subsampling=0)
        # Link without replacing any competing file. Remove the temporary only
        # after the completed file is committed to its final name.
        try:
            os.link(temporary, path)
        except (OSError, NotImplementedError):
            if path.exists():
                raise ProtocolError(f'Output file already exists: {path}')
            os.rename(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def catalog_forensic_report(data: bytes) -> dict:
    """Human-readable, offline catalog examination, NEVER a recovery claim.

    Catalog ranges may be internal camera addresses. Their semantics are not
    established, and a nonzero record is not proof of retrievable pixel data.
    """
    if len(data) != CATALOG_BYTES:
        raise ProtocolError(f'Catalog must be {CATALOG_BYTES} bytes')
    records = []
    for offset in range(0, CATALOG_BYTES, CATALOG_ENTRY_BYTES):
        b = data[offset:offset + CATALOG_ENTRY_BYTES]
        if b[0] == 0:
            break
        records.append({
            'slot': offset//CATALOG_ENTRY_BYTES+1,
            'marker': f'0x{b[0]:02x}',
            'record_hex': b.hex(' '),
            'address_start': f'0x{int.from_bytes(b[1:4], "big"):06x}',
            'address_end': f'0x{int.from_bytes(b[4:7], "big"):06x}',
            'supported_still': b[0] == 0x56,
        })
    suspicious = [r for r in records if not r['supported_still']]
    return {
        'catalog_records': len(records),
        'supported_640x480_stills': sum(r['supported_still'] for r in records),
        'unrecognized_slots': suspicious,
        'records': records,
        'verdict': ('No photo data for any unsupported slot is contained in this '
                    'catalog. Address metadata alone cannot reconstruct an image. '
                    'The XP USB capture contains only seven image payloads; the '
                    'eighth image cannot be recovered offline from those files.'),
        'experimental_probe': ('There is an opt-in, bounded extra-stream probe. It '
                               'may time out or return stale/duplicate data; it '
                               'does not target an address and must not be '
                               'considered proven slot-1 recovery.'),
    }


@contextlib.contextmanager
def camera_single_instance_lock():
    """Prevent two PalmClix instances sending commands simultaneously."""
    cache = pathlib.Path.home()/'.cache'/'PalmClix'
    cache.mkdir(parents=True, exist_ok=True)
    busy = ('Another PalmClix camera session is running. '
            'Close the other importer; do not retry simultaneously.')
    with (cache/'camera.lock').open('a+b') as fd:
        if fcntl is not None:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProtocolError(busy) from exc
            try:
                yield
            finally:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        else:
            fd.seek(0)
            try:
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ProtocolError(busy) from exc
            try:
                yield
            finally:
                fd.seek(0)
                msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)


def forensic_extra_probe(dev, output: pathlib.Path, existing_raw: list[pathlib.Path],
                         *, verbose=False, json_progress=False):
    """EXPERIMENTAL: one additional 640x480 stream read AFTER all known good frames.

    Only the already observed 0x03 bulk-read command type is used. There is no
    direct slot-address command; this cannot specifically request the 0x01 slot.
    The trial may time out or temporarily disturb the camera; never run it on
    photos not already backed up. Do not repeat it after a timeout.
    """
    recovery = output/'Recovery'
    recovery.mkdir(exist_ok=True)
    report = {'attempted': True, 'status': 'not-started',
              'warning': 'Unverified extra stream, NOT confirmed photo 8 or catalog slot 1.'}
    candidate = bytearray()
    try:
        for chunk_index in range(10):
            size = 32768 if chunk_index < 9 else 12288
            # One bounded attempt; do not retry timeout, reset device, or advance.
            candidate.extend(read_chunk(dev, size, 0, verbose, timeout=2500))
        report['bytes_returned'] = len(candidate)
        if len(candidate) == FRAME_SIZE:
            digest = hashlib.sha256(candidate).hexdigest()
            existing_hashes = set()
            for f in existing_raw:
                raw = f.read_bytes()
                header = f'P5\n{WIDTH} {HEIGHT}\n255\n'.encode()
                existing_hashes.add(hashlib.sha256(raw[len(header):]).hexdigest())
            duplicate = digest in existing_hashes
            flat = len(set(candidate[::101])) < 3
            report.update({'sha256': digest, 'duplicate_of_known_frame': duplicate,
                           'low_variation_sample': flat})
            if duplicate or flat:
                report['status'] = 'returned-duplicate-or-padding'
            else:
                save_bytes_safely(recovery/'EXPERIMENTAL_extra_stream.pgm',
                                  f'P5\n{WIDTH} {HEIGHT}\n255\n'.encode()+candidate)
                report['status'] = 'unverified-candidate-saved'
                report['candidate_path'] = 'Recovery/EXPERIMENTAL_extra_stream.pgm'
                # Deliberately leave conversion for offline review; a stream of
                # correct length alone is not proof of a photograph.
    except Exception as exc:
        report['status'] = 'timed-out-or-usb-error'
        report['error'] = str(exc)
        report['bytes_returned'] = len(candidate)
    save_bytes_safely(recovery/'probe_report.json',
                      (json.dumps(report, indent=2)+'\n').encode())
    event('recovery', report, json_progress)
    return report


def transfer(dev, requested: str, output: pathlib.Path, *, fmt='none',
             verbose=False, json_progress=False, profile='dsc-matched',
             probe_extra=False):
    """One carefully bounded transfer. Never attempts undocumented recovery."""
    if output.exists() and any(output.iterdir()):
        raise ProtocolError(f'Output folder is not empty: {output}; choose a new folder.')
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / 'Raw' if fmt != 'none' else output
    photos_dir = output / 'Photos'
    diagnostics_dir = output / 'Protocol'
    raw_dir.mkdir(exist_ok=True)
    diagnostics_dir.mkdir(exist_ok=True)
    if profile not in ('dsc-matched', 'legacy'):
        raise ProtocolError(f'Unknown color profile: {profile}')
    if fmt not in ('none', 'png', 'jpeg', 'both'):
        raise ProtocolError(f'Unsupported output format: {fmt}')
    if fmt != 'none':
        photos_dir.mkdir(exist_ok=True)
    # The captured sequence begins by requesting the camera MODEL ID.
    # The XP recordings use 0x81 and 0x82 as initial host-side read markers.
    # Live hardware keeps the already successful 0x81 behavior; replays use
    # the marker recorded in their own capture. Image DATA marker remains 0x81.
    catalog_marker = getattr(dev, 'catalog_marker', 0x81)
    ctrl_out(dev, 6, 0xf0, 0, verbose)
    expect_status(dev, verbose)
    header = ctrl_in(dev, 4, verbose)
    model = model_information(header)
    event('metadata', model, json_progress)
    # Count and types are read from CONFIG/0x20 and its 0x4000-byte catalog.
    ctrl_out(dev, 6, 0xa0, 0x50, verbose)
    expect_status(dev, verbose)
    ctrl_out(dev, 6, 0xa0, 0, verbose)
    expect_status(dev, verbose)
    ctrl_out(dev, 6, 0xf0, 0, verbose)
    expect_status(dev, verbose)
    first_bulk = read_chunk(dev, 4, catalog_marker, verbose)
    if first_bulk != header:
        raise ProtocolError(f'Metadata mismatch between control IN ({header.hex()}) '
                            f'and initial bulk IN ({first_bulk.hex()}); aborting.')
    save_bytes_safely(diagnostics_dir / 'metadata_4b.bin', header)
    save_bytes_safely(diagnostics_dir / 'first_bulk_4b.bin', first_bulk)
    ctrl_out(dev, 0xc0, 0, catalog_marker, verbose)
    for _ in range(3):
        ctrl_out(dev, 6, 0xa0, 0, verbose)
        expect_status(dev, verbose)
    ctrl_out(dev, 6, 0x20, 0, verbose)
    expect_status(dev, verbose)
    prelude = read_chunk(dev, CATALOG_BYTES, catalog_marker, verbose)
    save_bytes_safely(diagnostics_dir / 'allocation_catalog_16384.bin', prelude)
    # Complete the recorded catalog read/clear sequence before validating
    # entries. Even unsupported formats should leave the catalog register.
    ctrl_out(dev, 0xc0, 0, catalog_marker, verbose)
    ctrl_out(dev, 6, 0xa0, 0, verbose)
    expect_status(dev, verbose)
    entries = parse_catalog(prelude)
    count = len(entries)
    if probe_extra and not (count == 7 and entries[0]['catalog_slot'] == 2 and
                            prelude[0] == 0x01 and prelude[8*16] == 0):
        raise ProtocolError('Extra-frame probe is restricted to the verified 8-slot/7-photo catalog. No image reads sent.')
    skipped = entries[0]['catalog_slot'] - 1 if entries else 0
    # The camera's remaining-shot display is not a count of valid image entries.
    # Report physical slots and recognized photos separately without guessing
    # whether a 0x01 slot has recoverable pixel data.
    catalog_report = {
        'valid_photos': count,
        'occupied_slots': count + skipped,
        'excluded_slots': skipped,
        'excluded_slot_reason': ('Leading 0x01 entry observed in successful XP '
                                 'seven-photo download; contents unknown') if skipped else None,
        'entries': entries,
        'forensics': catalog_forensic_report(prelude),
    }
    event('catalog', {'count': count, 'occupied_slots': count + skipped,
                      'excluded_slots': skipped, 'types': [e['type'] for e in entries],
                      'skipped_leading_slots': skipped,
                      'source': '16-byte allocation table entries'}, json_progress)
    if skipped:
        print('CATALOG: Excluding leading 0x01 slot (observed in successful XP '
              '7-photo download); applying the verified 7-photo behavior.',
              file=sys.stderr, flush=True)
    if requested != 'auto' and int(requested) != count:
        raise ProtocolError(f'Camera allocation catalog contains {count} supported '
                            f'photos, not the requested {requested}. Stopped before DATA transfer.')
    if count == 0:
        save_bytes_safely(diagnostics_dir / 'catalog_report.json',
                          (json.dumps(catalog_report, indent=2) + '\n').encode('utf-8'))
        event('done', {'count': 0, 'output': str(output),
                       'photos': str(photos_dir) if fmt != 'none' else str(raw_dir)}, json_progress)
        return 0
    ctrl_out(dev, 0xc0, 0, 0x00, verbose)
    ctrl_out(dev, 6, 0x30, 0, verbose)
    expect_status(dev, verbose)

    event('stage', {'stage': 'transfer', 'count': count}, json_progress)
    captured_raw = []
    for photo in range(count):
        marker = 0x81 if photo == 0 else 0x00
        payload = bytearray()
        for chunk_number in range(10):
            transfer_size = 32768 if chunk_number < 9 else 12288
            payload.extend(read_chunk(dev, transfer_size, marker, verbose))
            event('chunk', {'photo': photo + 1, 'total_photos': count,
                            'chunk': chunk_number + 1, 'total_chunks': 10,
                            'completed_chunks': photo * 10 + chunk_number + 1,
                            'all_chunks': count * 10}, json_progress)
        if len(payload) != FRAME_SIZE:
            raise ProtocolError(f'Frame {photo + 1}: expected {FRAME_SIZE} bytes, got {len(payload)}')
        stem = f'PalmClix_{photo + 1:02d}'
        raw_path = raw_dir / f'{stem}.pgm'
        save_bytes_safely(raw_path, f'P5\n{WIDTH} {HEIGHT}\n255\n'.encode() + payload)
        captured_raw.append(raw_path)
        # Preserve captured ordering: boundary command follows every frame.
        ctrl_out(dev, 0xc0, 0, marker, verbose)
        event('transfer', {'index': photo + 1, 'total': count, 'raw_path': str(raw_path)}, json_progress)
    recovery_result = None
    if probe_extra:
        recovery_result = forensic_extra_probe(dev, output, captured_raw,
                                               verbose=verbose, json_progress=json_progress)
    # End-of-sequence command exactly as in the XP recording, including after
    # an optional experimental read. The extra read itself is NOT recorded.
    ctrl_out(dev, 6, 0xa0, 0, verbose)
    expect_status(dev, verbose)
    # The catalog report does not assert excluded slot contents are recoverable.
    save_bytes_safely(diagnostics_dir / 'catalog_report.json',
                      (json.dumps(catalog_report, indent=2) + '\n').encode('utf-8'))
    # Decode only AFTER the camera's proven end-of-session sequence. Slow image
    # processing must not disturb unknown camera-side timing requirements.
    if fmt != 'none':
        event('stage', {'stage': 'decode', 'count': count}, json_progress)
        from decode_palmclix import convert_raw
        from PIL import Image
        for photo in range(count):
            stem = f'PalmClix_{photo + 1:02d}'
            raw_path = raw_dir / f'{stem}.pgm'
            rgb = convert_raw(raw_path, profile=profile)
            img = Image.fromarray(rgb, 'RGB')
            destinations = ([('png', 'PNG')] if fmt == 'png' else
                            [('jpg', 'JPEG')] if fmt == 'jpeg' else
                            [('png', 'PNG'), ('jpg', 'JPEG')])
            paths = []
            for extension, encoder in destinations:
                image_path = photos_dir / f'{stem}.{extension}'
                save_image_atomically(img, image_path, encoder)
                paths.append(str(image_path))
            event('photo', {'index': photo + 1, 'total': count,
                            'raw_path': str(raw_path), 'image_path': paths[0],
                            'additional_paths': paths[1:]}, json_progress)
    # Candidate processing happens only AFTER the recorded camera shutdown and
    # normal image decoding. It never becomes an automatic trusted gallery item.
    if recovery_result and recovery_result.get('status') == 'unverified-candidate-saved':
        try:
            from PIL import Image
            from decode_palmclix import convert_raw
            candidate_path = output / recovery_result['candidate_path']
            preview = output / 'Recovery' / 'EXPERIMENTAL_extra_stream.png'
            save_image_atomically(Image.fromarray(convert_raw(candidate_path, profile=profile), 'RGB'),
                                  preview, 'PNG')
            recovery_result['preview_path'] = str(preview.relative_to(output))
        except Exception as exc:
            # Preserve original seven photos and optional raw recovery data.
            recovery_result['preview_error'] = str(exc)
    manifest = {
        'app_version': '1.0.0', 'imported_utc': datetime.now(timezone.utc).isoformat(),
        'camera_usb_id': f'{VID:04x}:{PID:04x}', 'model_id': model['model_id'],
        'valid_photos': count, 'occupied_slots': count + skipped,
        'excluded_slots': skipped, 'format': fmt, 'color_profile': profile,
        'experimental_recovery_probe': recovery_result, 'images': [],
        'note': '0x01 excluded slot has not been proven recoverable; extra stream, if any, is UNVERIFIED',
    }
    for photo in range(count):
        stem = f'PalmClix_{photo + 1:02d}'
        raw = raw_dir / f'{stem}.pgm'
        record = {'catalog_slot': entries[photo]['catalog_slot'],
                  'raw_file': str(raw.relative_to(output)),
                  'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}
        if fmt != 'none':
            extensions = ['png', 'jpg'] if fmt == 'both' else ['png' if fmt == 'png' else 'jpg']
            record['photo_files'] = [str((photos_dir / f'{stem}.{extension}').relative_to(output))
                                     for extension in extensions]
            record['photo_file'] = record['photo_files'][0]
            record['photo_sha256'] = {extension: hashlib.sha256(
                (photos_dir / f'{stem}.{extension}').read_bytes()).hexdigest()
                for extension in extensions}
        manifest['images'].append(record)
    save_bytes_safely(diagnostics_dir / 'import_manifest.json',
                      (json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    event('done', {'count': count, 'excluded_slots': skipped,
                   'output': str(output),
                   'photos': str(photos_dir) if fmt != 'none' else str(raw_dir)}, json_progress)
    return count


def pcap_events(filename: pathlib.Path):
    with filename.open('rb') as f:
        head = f.read(24)
        if len(head) != 24 or head[:4] != b'\xd4\xc3\xb2\xa1' or struct.unpack_from('<I', head, 20)[0] != 249:
            raise ProtocolError('Expected little-endian USBPcap .pcap, linktype 249')
        events = []
        while record := f.read(16):
            if len(record) != 16:
                raise ProtocolError('Truncated pcap record')
            _, _, inclen, _ = RECORD.unpack(record)
            packet = f.read(inclen)
            if len(packet) != inclen:
                raise ProtocolError('Truncated pcap packet')
            if len(packet) < USB_HEADER.size:
                continue
            h, _, status, _, info, _, _, ep, transfer, length = USB_HEADER.unpack_from(packet)
            if h < USB_HEADER.size or h > len(packet):
                raise ProtocolError('Bad USBPcap record header')
            events.append(dict(endpoint=ep, transfer=transfer, incoming=bool(info & 1),
                               data=packet[h:], length=length, status=status))
    return events


class RecordedDevice:
    """Strict virtual USB device from the owner's ten-photo recording."""
    def __init__(self, capture):
        self.events = pcap_events(capture)[6:]  # skip enumeration only
        self.pos = 0
        # Initial control OUT data for 4-byte model read records marker byte.
        candidates = [e['data'][-1] for e in self.events
                      if e['transfer'] == 2 and not e['incoming']
                      and e['data'][:8] == bytes.fromhex('40 0c 03 00 04 00 01 00')]
        if len(candidates) != 1 or candidates[0] not in (0x81, 0x82):
            raise ProtocolError('Cannot identify supported initial read marker from capture')
        self.catalog_marker = candidates[0]

    def next(self):
        if self.pos >= len(self.events):
            raise ProtocolError('Replay passed end of trace')
        e = self.events[self.pos]
        self.pos += 1
        return e

    def ctrl_transfer(self, bm, req, value, index, data_or_length, timeout=None):
        e = self.next()
        size = data_or_length if isinstance(data_or_length, int) else len(data_or_length)
        expected = struct.pack('<BBHHH', bm, req, value, index, size)
        if bm == 0x40:
            expected += bytes(data_or_length)
        if e['transfer'] != 2 or e['incoming'] or e['data'] != expected:
            raise ProtocolError(f'Control replay mismatch at event {self.pos}: expected {expected.hex()}, actual {e}')
        reply = self.next()
        if reply['transfer'] != 2 or not reply['incoming']:
            raise ProtocolError(f'Missing control reply at event {self.pos}')
        return len(data_or_length) if bm == 0x40 else reply['data']

    def read(self, ep, n, timeout=None):
        req = self.next()
        if req['transfer'] != 3 or req['incoming'] or req['endpoint'] != ep:
            raise ProtocolError(f'Unexpected bulk request at event {self.pos}')
        reply = self.next()
        if reply['transfer'] != 3 or not reply['incoming'] or reply['endpoint'] != ep or len(reply['data']) != n:
            raise ProtocolError(f'Bad bulk response at event {self.pos}: {len(reply["data"])} vs {n}')
        return reply['data']

    def finished(self):
        if self.pos != len(self.events):
            raise ProtocolError(f'Replay has {len(self.events) - self.pos} unmatched events')


def _configuration_missing(error):
    """PyUSB raises USBError('Configuration not set') for USB config 0.

    Do not interpret other USB errors (permissions, BUSY, disconnect) as an
    unconfigured device. In particular, never reset an already configured
    camera just to recover from an unrelated failure.
    """
    return 'configuration not set' in str(error).lower()


def ensure_camera_configuration(dev, *, verbose=False):
    """Select a USB configuration only if the device has none active.

    Configuring an already configured device can reset endpoint/device state.
    This deliberately avoids unconditional dev.set_configuration().
    """
    try:
        cfg = dev.get_active_configuration()
        if verbose:
            print(f'USB: configuration {cfg.bConfigurationValue} already active; '
                  'leaving it unchanged.', file=sys.stderr, flush=True)
        return cfg, False
    except Exception as exc:
        if not _configuration_missing(exc):
            raise ProtocolError(f'Could not determine USB configuration: {exc}') from exc

    # Read the descriptor (no proprietary command) to find the device's
    # supported configuration; the PalmClix has one, value 1.
    if dev.bNumConfigurations != 1:
        raise ProtocolError(f'Expected one PalmClix configuration; '
                            f'found {dev.bNumConfigurations}. Not changing it.')
    cfg_desc = dev[0]
    desired = cfg_desc.bConfigurationValue
    if desired != 1:
        raise ProtocolError(f'Unexpected configuration value {desired}; refusing to select it.')
    print('USB: PalmClix is present but unconfigured. '
          'Selecting configuration 1 once (no camera photo commands).',
          file=sys.stderr, flush=True)
    try:
        dev.set_configuration(desired)
        cfg = dev.get_active_configuration()
    except Exception as exc:
        raise ProtocolError('PalmClix has no active USB configuration, '
                            f'and selecting configuration {desired} failed: {exc}. '
                            'Release the camera from UTM/Wine, reconnect it to macOS, '
                            'and run --usb-status. No camera download commands were sent.') from exc
    if cfg.bConfigurationValue != desired:
        raise ProtocolError(f'USB configuration verification failed: '
                            f'expected {desired}, got {cfg.bConfigurationValue}.')
    return cfg, True


def bundled_libusb_backend():
    """Use PyInstaller-bundled libusb, or ordinary PyUSB discovery from source."""
    packaged = getattr(sys, '_MEIPASS', None)
    if not packaged:
        return None
    name = 'libusb-1.0.dll' if os.name == 'nt' else 'libusb-1.0.0.dylib'
    library = pathlib.Path(packaged) / name
    if not library.is_file():
        raise ProtocolError(f'Standalone app is missing its bundled {name}; '
                            'please rebuild the app.')
    import usb.backend.libusb1
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: str(library))
    if backend is None:
        raise ProtocolError(f'Could not load bundled libusb library: {library}')
    return backend


def open_camera(*, verbose=False):
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise ProtocolError('PyUSB missing. Install requirements.txt') from exc
    backend = bundled_libusb_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        raise ProtocolError('PalmClix 2770:9120 not found. Release it from UTM and close Wine. '
                            'On Windows, install the WinUSB driver for the camera with Zadig (see README).')
    try:
        cfg, changed = ensure_camera_configuration(dev, verbose=verbose)
        interface = cfg[(0, 0)].bInterfaceNumber
        try:
            usb.util.claim_interface(dev, interface)
        except Exception as exc:
            raise ProtocolError(f'Unable to claim PalmClix interface {interface}: {exc}. '
                                'Close Wine and release the camera from the XP VM.') from exc
        if verbose:
            print(f'USB: claimed interface {interface}; configuration '
                  f'{cfg.bConfigurationValue} ({"newly selected" if changed else "unchanged"}).',
                  file=sys.stderr, flush=True)
        return dev
    except Exception:
        usb.util.dispose_resources(dev)
        raise


def usb_status(*, prepare=False, verbose=False):
    """Read standard USB configuration status; optionally configure/claim.

    --usb-status doesn't issue proprietary commands or change configuration.
    --prepare-usb conditionally configures an unconfigured camera, then claims
    and releases interface 0; it does NOT request photographs.
    """
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise ProtocolError('PyUSB missing. Install requirements.txt') from exc
    backend = bundled_libusb_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        raise ProtocolError('PalmClix 2770:9120 not detected by libusb.')
    if not prepare:
        try:
            cfg = dev.get_active_configuration()
            print(f'USB status: configured (value={cfg.bConfigurationValue}); '
                  'no changes made.')
        except Exception as exc:
            if _configuration_missing(exc):
                print('USB status: UNCONFIGURED (USB configuration 0). '
                      'Try --prepare-usb; no changes were made.')
            else:
                raise ProtocolError(f'Cannot read active configuration: {exc}') from exc
        finally:
            usb.util.dispose_resources(dev)
        return 0
    camera = open_camera(verbose=verbose)
    try:
        print('USB prepare: configuration active; interface 0 successfully claimed. '
              'No proprietary commands sent; no photos read.')
    finally:
        usb.util.dispose_resources(camera)
    return 0


def inspect_device():
    try:
        import usb.core
    except ImportError as exc:
        raise ProtocolError('PyUSB missing. Install requirements.txt') from exc
    backend = bundled_libusb_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        print('PalmClix 2770:9120 not detected')
        return 1
    print(f'Detected device: {dev.idVendor:04x}:{dev.idProduct:04x}, configurations={dev.bNumConfigurations}')
    for cfg in dev:
        print(f'Configuration {cfg.bConfigurationValue}')
        for itf in cfg:
            print(f'  Interface {itf.bInterfaceNumber}, alternate {itf.bAlternateSetting}, class=0x{itf.bInterfaceClass:02x}')
            for ep in itf:
                print(f'    Endpoint 0x{ep.bEndpointAddress:02x}, attrs=0x{ep.bmAttributes:02x}, max-packet={ep.wMaxPacketSize}')
    print('INSPECT mode sends no vendor-specific commands.')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true', help='USB descriptors only')
    mode.add_argument('--usb-status', action='store_true', help='Read active USB configuration without changing it')
    mode.add_argument('--prepare-usb', action='store_true', help='Select USB config only if unconfigured; claim and release interface; no camera commands')
    mode.add_argument('--ready-check', action='store_true', help='Safely configure and claim USB interface, then release; no photo commands')
    mode.add_argument('--forensics', type=pathlib.Path, metavar='CATALOG.BIN', help='Read-only offline analysis of known and unknown catalog slots')
    mode.add_argument('--catalog', type=pathlib.Path, metavar='FILE.BIN', help='Offline: inspect 16 KB camera allocation table')
    mode.add_argument('--simulate', type=pathlib.Path, metavar='CAPTURE.PCAP', help='Safe offline full USB replay')
    mode.add_argument('--download', metavar='N|auto', help='Live download; auto counts 0x56 photos, excluding the single verified leading 0x01 slot')
    p.add_argument('--profile', choices=['dsc-matched','legacy'], default='dsc-matched',
                   help='Color: improved DSC-style fit (default) or earlier v0.4 look')
    p.add_argument('--probe-extra-frame', action='store_true',
                   help='Experimental: AFTER the verified 7-photo read, attempt at most one additional raw frame')
    p.add_argument('--i-accept-experimental-probe', action='store_true',
                   help='Second opt-in required for an unverified read past the known photo stream')
    p.add_argument('--format', choices=['none', 'png', 'jpeg', 'both'], default='none', help='Convert to PNG, JPEG, or both; always preserve original raw PGM')
    p.add_argument('--output', type=pathlib.Path, default=pathlib.Path('palmclix_output'))
    p.add_argument('--i-accept-experimental-usb', action='store_true', help='Required for live commands')
    p.add_argument('--json-progress', action='store_true', help='Machine-readable progress events for native GUI')
    p.add_argument('--verbose', action='store_true')
    a = p.parse_args(argv)
    try:
        if a.inspect:
            return inspect_device()
        if a.usb_status:
            return usb_status()
        if a.prepare_usb or a.ready_check:
            return usb_status(prepare=True, verbose=a.verbose)
        if a.forensics:
            print(json.dumps(catalog_forensic_report(a.forensics.read_bytes()), indent=2))
            return 0
        if a.catalog:
            entries = parse_catalog(a.catalog.read_bytes())
            print(f'Allocation catalog: {len(entries)} supported 640x480 photographs')
            if entries and entries[0]['catalog_slot'] > 1:
                print('  Leading 0x01 catalog slot excluded (confirmed by XP capture).')
            for entry in entries:
                print('  catalog slot {catalog_slot}, photo {index}: type=0x{type}, {width}x{height}, '
                      '{byte_count} raw bytes'.format(**entry))
            return 0
        if a.simulate:
            dev = RecordedDevice(a.simulate)
            transfer(dev, 'auto', a.output, fmt=a.format, verbose=a.verbose,
                     json_progress=a.json_progress, profile=a.profile)
            dev.finished()
            print('PASS: Full USB transfer sequence matches recorded XP session.', file=sys.stderr)
            return 0
        if a.download != 'auto':
            try:
                n = int(a.download)
                if not 0 <= n <= MAX_PHOTOS:
                    raise ValueError
            except ValueError:
                p.error(f'--download must be auto or an integer 0..{MAX_PHOTOS}')
        if a.probe_extra_frame and not a.i_accept_experimental_probe:
            p.error('--probe-extra-frame requires --i-accept-experimental-probe; backup photos with XP first')
        if a.probe_extra_frame and a.download != 'auto':
            p.error('Extra-frame probe requires --download auto')
        if not a.i_accept_experimental_usb:
            p.error('Live commands require --i-accept-experimental-usb')
        import usb.util
        with camera_single_instance_lock():
            dev = open_camera(verbose=a.verbose)
            try:
                transfer(dev, a.download, a.output, fmt=a.format,
                         verbose=a.verbose, json_progress=a.json_progress,
                         profile=a.profile, probe_extra=a.probe_extra_frame)
            finally:
                usb.util.dispose_resources(dev)
        return 0
    except (ProtocolError, OSError) as exc:
        event('error', {'message': str(exc)}, a.json_progress)
        print('ERROR:', exc, file=sys.stderr)
        return 1
    except Exception as exc:
        event('error', {'message': f'{type(exc).__name__}: {exc}'}, a.json_progress)
        print(f'ERROR ({type(exc).__name__}): {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
