"""New release regression coverage. No device is accessed by these tests."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from palmclix import ProtocolError, RecordedDevice, bundled_libusb_backend, transfer


class WorkflowTests(unittest.TestCase):
    def run_capture(self, path, wanted, skipped):
        if not pathlib.Path(path).exists():
            self.skipTest('private USB recording is not included in the public repository')
        with tempfile.TemporaryDirectory() as temporary:
            target = pathlib.Path(temporary) / 'import'
            camera = RecordedDevice(path)
            count = transfer(camera, 'auto', target, fmt='png')
            camera.finished()
            self.assertEqual(count, wanted)
            self.assertEqual(len(list((target / 'Raw').glob('PalmClix_*.pgm'))), wanted)
            self.assertEqual(len(list((target / 'Photos').glob('PalmClix_*.png'))), wanted)
            self.assertTrue((target / 'Photos' / 'PalmClix_01.png').stat().st_size > 1000)
            catalog = json.loads((target / 'Protocol' / 'catalog_report.json').read_text())
            manifest = json.loads((target / 'Protocol' / 'import_manifest.json').read_text())
            self.assertEqual(catalog['valid_photos'], wanted)
            self.assertEqual(catalog['occupied_slots'], wanted + skipped)
            self.assertEqual(manifest['excluded_slots'], skipped)
            self.assertEqual(len(manifest['images']), wanted)
            self.assertEqual(manifest['images'][0]['catalog_slot'], skipped + 1)
            self.assertEqual(len(manifest['images'][0]['raw_sha256']), 64)

    def test_full_ten_photo_replay_and_decode(self):
        self.run_capture(ROOT / 'reference_capture.pcap', 10, 0)

    def test_full_seven_photo_replay_and_decode(self):
        self.run_capture(ROOT / 'tests/fixtures/seven_photo_capture.pcap', 7, 1)

    def test_nonpacked_mode_uses_system_libusb(self):
        with patch.object(sys, '_MEIPASS', None, create=True):
            self.assertIsNone(bundled_libusb_backend())

    def test_packaged_mode_rejects_missing_libusb(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(sys, '_MEIPASS', temporary, create=True):
                with self.assertRaisesRegex(ProtocolError, 'missing its bundled libusb'):
                    bundled_libusb_backend()


if __name__ == '__main__':
    unittest.main()
