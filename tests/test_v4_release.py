"""Release-candidate checks; run entirely offline, no camera USB commands."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from palmclix import RecordedDevice, ProtocolError, transfer


class ReleaseCandidateTests(unittest.TestCase):
    def simulate(self, fixture, fmt):
        if not (ROOT / fixture).exists():
            self.skipTest('private USB recording is not included in the public repository')
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder) / 'new_import'
            device = RecordedDevice(ROOT / fixture)
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                total = transfer(device, 'auto', root, fmt=fmt, json_progress=True)
                device.finished()
            self.assertIn(total, (7, 10))
            self.assertEqual(len(list((root / 'Raw').glob('*.pgm'))), total)
            messages = []
            for line in output.getvalue().splitlines():
                if line.startswith('PALMCLIX_EVENT '):
                    messages.append(json.loads(line[len('PALMCLIX_EVENT '):]))
            chunks = [m for m in messages if m['event'] == 'chunk']
            self.assertEqual(len(chunks), total * 10)
            self.assertEqual([m['completed_chunks'] for m in chunks], list(range(1, total * 10 + 1)))
            stages = [m['stage'] for m in messages if m['event'] == 'stage']
            self.assertEqual(stages, (['transfer'] if fmt == 'none' else ['transfer', 'decode']))
            self.assertEqual(messages[-1]['event'], 'done')
            manifest_path = root / 'Protocol' / 'import_manifest.json'
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest['app_version'], '1.0.0')
            self.assertEqual(manifest['valid_photos'], total)
            self.assertEqual(len(manifest['images']), total)
            if fmt != 'none':
                extensions = ['png', 'jpg'] if fmt == 'both' else ['png' if fmt == 'png' else 'jpg']
                for ext in extensions:
                    self.assertEqual(len(list((root / 'Photos').glob('*.' + ext))), total)
                for record in manifest['images']:
                    self.assertEqual(len(record['photo_sha256']), len(extensions))
                    for ext in extensions:
                        self.assertEqual(len(record['photo_sha256'][ext]), 64)
            else:
                self.assertEqual(len(list(root.glob('*.pgm'))), total)
            return total

    def test_ten_photo_both_formats(self):
        self.assertEqual(self.simulate('reference_capture.pcap', 'both'), 10)

    def test_seven_photo_both_formats(self):
        self.assertEqual(self.simulate('tests/fixtures/seven_photo_capture.pcap', 'both'), 7)

    def test_ten_photo_png_progress(self):
        self.assertEqual(self.simulate('reference_capture.pcap', 'png'), 10)

    def test_seven_photo_jpeg_progress(self):
        self.assertEqual(self.simulate('tests/fixtures/seven_photo_capture.pcap', 'jpeg'), 7)

    def test_previous_import_not_overwritten(self):
        if not (ROOT / 'reference_capture.pcap').exists():
            self.skipTest('private USB recording is not included in the public repository')
        with tempfile.TemporaryDirectory() as folder:
            destination = pathlib.Path(folder) / 'import'
            destination.mkdir()
            precious = destination / 'PalmClix_01.png'
            precious.write_bytes(b'MY-ORIGINAL')
            with self.assertRaisesRegex(ProtocolError, 'not empty'):
                transfer(RecordedDevice(ROOT / 'reference_capture.pcap'), 'auto', destination, fmt='both')
            self.assertEqual(precious.read_bytes(), b'MY-ORIGINAL')

    def test_unknown_catalog_type_fails_before_frame_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            # Invalid catalog marker must be rejected before any image stream commands.
            data = bytearray((ROOT / 'tests/fixtures/after_power_loss_catalog.bin').read_bytes())
            data[16] = 0x7e
            from palmclix import parse_catalog
            with self.assertRaisesRegex(ProtocolError, 'unsupported'):
                parse_catalog(bytes(data))


if __name__ == '__main__':
    unittest.main()
