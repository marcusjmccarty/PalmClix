import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from palmclix import (CATALOG_BYTES, REFERENCE_HEADER, RecordedDevice,
                      ProtocolError, model_information, parse_catalog, transfer)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.catalog = bytearray(CATALOG_BYTES)
        for i in range(10):
            self.catalog[i*16] = 0x56

    def test_id_is_not_photo_count(self):
        self.assertEqual(model_information(REFERENCE_HEADER)['model_id'], '09 05 01 19')
        self.assertNotIn('count', model_information(REFERENCE_HEADER))

    def test_catalog_counts_ten(self):
        result = parse_catalog(bytes(self.catalog))
        self.assertEqual(len(result), 10)
        self.assertTrue(all(row['type'] == '56' and row['byte_count'] == 307200 for row in result))

    def test_other_count_from_catalog(self):
        for count in [0, 1, 3, 12]:
            table = bytearray(CATALOG_BYTES)
            for i in range(count):
                table[i*16] = 0x56
            self.assertEqual(len(parse_catalog(bytes(table))), count)

    def test_unsupported_format_stops(self):
        self.catalog[3*16] = 0x53  # SQ905 clip; no decoder implemented
        with self.assertRaisesRegex(ProtocolError, 'unsupported'):
            parse_catalog(bytes(self.catalog))

    def test_post_power_loss_catalog_matches_seven_photos(self):
        data = (ROOT / 'tests/fixtures/after_power_loss_catalog.bin').read_bytes()
        photos = parse_catalog(data)
        self.assertEqual(len(photos), 7)
        self.assertEqual([e['catalog_slot'] for e in photos], list(range(2, 9)))
        self.assertTrue(all(e['type'] == '56' for e in photos))

    def test_01_only_allowed_in_first_slot_with_known_allocation(self):
        catalog = bytearray(CATALOG_BYTES)
        catalog[:16] = bytes.fromhex('01 0a 80 00 13 af ff 00 00 27 25 00 1f 28 00 2a')
        catalog[16] = 0x56
        self.assertEqual(len(parse_catalog(bytes(catalog))), 1)
        catalog[0] = 0x56
        catalog[16] = 0x01
        with self.assertRaisesRegex(ProtocolError, 'unsupported'):
            parse_catalog(bytes(catalog))
        catalog[0] = 0x01
        catalog[16] = 0x00
        with self.assertRaisesRegex(ProtocolError, 'no supported'):
            parse_catalog(bytes(catalog))
        catalog[16] = 0x56
        catalog[1] ^= 0x01
        with self.assertRaisesRegex(ProtocolError, 'unsupported'):
            parse_catalog(bytes(catalog))

    def test_corrupted_table_stops(self):
        with self.assertRaises(ProtocolError):
            parse_catalog(b'\x56')

    def test_captured_catalog_matches_expected_count(self):
        if not (ROOT / 'reference_capture.pcap').exists():
            self.skipTest('private USB recording is not included in the public repository')
        with tempfile.TemporaryDirectory() as folder:
            # Uses original 10-photo Windows capture; exact USB replay
            device = RecordedDevice(ROOT / 'reference_capture.pcap')
            n = transfer(device, 'auto', pathlib.Path(folder)/'output', fmt='none')
            self.assertEqual(n, 10)
            device.finished()
            raw = pathlib.Path(folder)/'output'
            self.assertEqual(len(list(raw.glob('PalmClix_*.pgm'))), 10)
            table = (raw/'Protocol'/'allocation_catalog_16384.bin').read_bytes()
            self.assertEqual(len(parse_catalog(table)), 10)


if __name__ == '__main__':
    unittest.main()
