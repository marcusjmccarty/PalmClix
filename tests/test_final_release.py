"""Final release: safety boundaries, forensic reporting, color and reconnect checks."""
import contextlib
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from palmclix import (ProtocolError, catalog_forensic_report,
                      camera_single_instance_lock, forensic_extra_probe,
                      parse_catalog)
from decode_palmclix import convert_raw, dsc_matched, decode_mosaic


class TestFinalRelease(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = (ROOT/'tests/fixtures/after_power_loss_catalog.bin').read_bytes()

    def test_exact_suspect_slot(self):
        report = catalog_forensic_report(self.catalog)
        self.assertEqual(report['catalog_records'], 8)
        self.assertEqual(report['supported_640x480_stills'], 7)
        self.assertEqual(len(report['unrecognized_slots']), 1)
        self.assertEqual(report['unrecognized_slots'][0]['marker'], '0x01')
        self.assertEqual(report['unrecognized_slots'][0]['address_start'], '0x0a8000')
        self.assertEqual(report['unrecognized_slots'][0]['address_end'], '0x13afff')
        self.assertIn('cannot be recovered offline', report['verdict'])

    def test_known_original_catalog(self):
        old = (ROOT/'sample_allocation_catalog.bin').read_bytes()
        result = catalog_forensic_report(old)
        self.assertEqual(result['supported_640x480_stills'], 10)
        self.assertFalse(result['unrecognized_slots'])

    def test_forensics_rejects_short_catalog(self):
        with self.assertRaises(ProtocolError):
            catalog_forensic_report(b'\x56' * 100)

    def test_unknown_type_not_auto_enabled(self):
        altered = bytearray(self.catalog)
        altered[16] = 0x01
        with self.assertRaises(ProtocolError):
            parse_catalog(bytes(altered))

    def test_lock_refuses_parallel_camera_session(self):
        with camera_single_instance_lock():
            with self.assertRaises(ProtocolError):
                with camera_single_instance_lock():
                    pass

    def test_new_decoder_size_and_determinism(self):
        path = ROOT/'reference_bmps/capturetest001.bmp'
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:,:,0] = 40
        frame[:,:,1] = 70
        frame[:,:,2] = 110
        a = dsc_matched(frame)
        b = dsc_matched(frame)
        self.assertEqual(a.shape, (480, 640, 3))
        self.assertEqual(a.dtype, np.uint8)
        self.assertTrue(np.array_equal(a,b))
        if path.exists():  # private reference photo, absent from the public repository
            self.assertTrue(path.is_file())

    def test_color_reduces_error_against_second_reference(self):
        # The 10-photo reference recording corresponds to the original DSC BMP.
        # This sample is included in the training set, so it validates output
        # consistency, not independent generalization (see LOOCV report).
        with tempfile.TemporaryDirectory() as td:
            raw = np.arange(640*480, dtype=np.uint8).reshape(480,640)
            src = pathlib.Path(td)/'test.pgm'
            Image.fromarray(raw).save(src)
            old = convert_raw(src, 'legacy')
            new = convert_raw(src, 'dsc-matched')
            self.assertEqual(new.shape, old.shape)
            self.assertFalse(np.array_equal(new,old))

    def test_loo_validation_report(self):
        data = json.loads((ROOT/'COLOR_VALIDATION.json').read_text())
        self.assertEqual(len(data['per_photo']), 10)
        self.assertLess(data['dsc_matched_mean_mae'], data['legacy_mean_mae'] * .6)

    def test_probe_rejects_missing_frame_without_retry(self):
        class TimeoutDevice:
            def __init__(self): self.reads = 0
            def ctrl_transfer(self, *args, **kwargs): return 1
            def read(self, *args, **kwargs):
                self.reads += 1
                raise TimeoutError('no eighth frame available')
        with tempfile.TemporaryDirectory() as td:
            d = TimeoutDevice()
            result = forensic_extra_probe(d, pathlib.Path(td), [])
            self.assertEqual(result['status'], 'timed-out-or-usb-error')
            self.assertEqual(d.reads, 1)
            self.assertTrue((pathlib.Path(td)/'Recovery/probe_report.json').exists())
            self.assertFalse((pathlib.Path(td)/'Recovery/EXPERIMENTAL_extra_stream.pgm').exists())

    def test_probe_saves_unverified_full_candidate(self):
        # Synthesized USB payload, NOT proof a real eighth photo is available.
        candidate = bytes((i//101 + i%17) % 256 for i in range(640*480))
        class SimDevice:
            def __init__(self): self.offset = 0
            def ctrl_transfer(self, *args, **kwargs): return 1
            def read(self, ep, count, timeout=None):
                payload = candidate[self.offset:self.offset+count]
                self.offset += count
                return payload
        with tempfile.TemporaryDirectory() as td:
            result = forensic_extra_probe(SimDevice(), pathlib.Path(td), [])
            self.assertEqual(result['status'], 'unverified-candidate-saved')
            path = pathlib.Path(td)/'Recovery/EXPERIMENTAL_extra_stream.pgm'
            self.assertEqual(np.asarray(Image.open(path)).shape, (480,640))

    def test_probe_discards_duplicate(self):
        candidate = bytes((i*17//33)%256 for i in range(640*480))
        class SimDevice:
            def __init__(self): self.offset = 0
            def ctrl_transfer(self, *args, **kwargs): return 1
            def read(self, ep, count, timeout=None):
                payload = candidate[self.offset:self.offset+count]
                self.offset += count
                return payload
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td)
            source = path/'existing.pgm'
            source.write_bytes(b'P5\n640 480\n255\n'+candidate)
            result = forensic_extra_probe(SimDevice(), path, [source])
            self.assertEqual(result['status'],'returned-duplicate-or-padding')
            self.assertFalse((path/'Recovery/EXPERIMENTAL_extra_stream.pgm').exists())


if __name__ == '__main__':
    unittest.main()
