"""Offline USB setup tests using doubles, never touching actual USB hardware."""
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from palmclix import ProtocolError, ensure_camera_configuration, open_camera, usb_status


class Unconfigured(Exception):
    def __str__(self):
        return '[Errno None] Configuration not set'


class FakeConfiguration:
    bConfigurationValue = 1
    def __getitem__(self, key):
        assert key == (0, 0)
        return types.SimpleNamespace(bInterfaceNumber=0)


class FakeDevice:
    bNumConfigurations = 1
    def __init__(self, active=True):
        self.active = active
        self.configured_count = 0
        self.get_calls = 0
        self.cfg = FakeConfiguration()
    def get_active_configuration(self):
        self.get_calls += 1
        if not self.active:
            raise Unconfigured()
        return self.cfg
    def __getitem__(self, index):
        assert index == 0
        return self.cfg
    def set_configuration(self, value):
        assert value == 1
        self.configured_count += 1
        self.active = True


class SetupTests(unittest.TestCase):
    def test_already_configured_must_not_reset(self):
        dev = FakeDevice(active=True)
        cfg, changed = ensure_camera_configuration(dev)
        self.assertIs(cfg, dev.cfg)
        self.assertFalse(changed)
        self.assertEqual(dev.configured_count, 0)

    def test_unconfigured_device_configured_once(self):
        dev = FakeDevice(active=False)
        cfg, changed = ensure_camera_configuration(dev)
        self.assertEqual(cfg.bConfigurationValue, 1)
        self.assertTrue(changed)
        self.assertEqual(dev.configured_count, 1)

    def test_other_usb_error_never_triggers_configuration(self):
        dev = FakeDevice(active=False)
        def raise_busy():
            raise RuntimeError('Resource busy')
        dev.get_active_configuration = raise_busy
        with self.assertRaisesRegex(ProtocolError, 'Resource busy'):
            ensure_camera_configuration(dev)
        self.assertEqual(dev.configured_count, 0)

    def test_no_unrecognized_configuration_selected(self):
        dev = FakeDevice(active=False)
        dev.cfg.bConfigurationValue = 2
        with self.assertRaisesRegex(ProtocolError, 'Unexpected configuration value'):
            ensure_camera_configuration(dev)
        self.assertEqual(dev.configured_count, 0)

    def _fake_usb(self, dev):
        usb = types.ModuleType('usb')
        core = types.ModuleType('usb.core')
        util = types.ModuleType('usb.util')
        core.find = lambda **kwargs: dev
        self.claimed = []
        self.disposed = []
        util.claim_interface = lambda d, i: self.claimed.append((d, i))
        util.dispose_resources = lambda d: self.disposed.append(d)
        usb.core, usb.util = core, util
        return {'usb':usb, 'usb.core':core, 'usb.util':util}

    def test_open_camera_claims_interface_after_configuration(self):
        dev = FakeDevice(active=False)
        with patch.dict(sys.modules, self._fake_usb(dev)):
            got = open_camera()
        self.assertIs(got, dev)
        self.assertEqual(dev.configured_count, 1)
        self.assertEqual(self.claimed, [(dev, 0)])

    def test_status_never_changes_configuration(self):
        dev = FakeDevice(active=False)
        with patch.dict(sys.modules, self._fake_usb(dev)):
            self.assertEqual(usb_status(), 0)
        self.assertEqual(dev.configured_count, 0)
        self.assertEqual(self.disposed, [dev])

    def test_prepare_configures_and_claims(self):
        dev = FakeDevice(active=False)
        with patch.dict(sys.modules, self._fake_usb(dev)):
            self.assertEqual(usb_status(prepare=True), 0)
        self.assertEqual(dev.configured_count, 1)
        self.assertEqual(self.claimed, [(dev, 0)])
        self.assertEqual(self.disposed, [dev])


if __name__ == '__main__':
    unittest.main()
