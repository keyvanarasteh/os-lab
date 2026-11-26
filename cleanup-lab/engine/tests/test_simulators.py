"""CLS-01 typed simulator cleanup against a fake simctl."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_lab import simulators  # noqa: E402
ROOT = str(pathlib.Path(__file__).resolve().parents[3])

GOOD = 'A1B2C3D4-1111-2222-3333-444455556666'
GONE = 'B1B2C3D4-1111-2222-3333-444455556666'
BOOTED = 'C1B2C3D4-1111-2222-3333-444455556666'


class FakeSimctl:
    def __init__(self):
        self.devices = {'com.apple.CoreSimulator.SimRuntime.iOS-18-0': [
            {'udid': GOOD, 'name': 'iPhone 16', 'state': 'Shutdown', 'isAvailable': True},
            {'udid': GONE, 'name': 'iPhone 8', 'state': 'Shutdown', 'isAvailable': False},
            {'udid': BOOTED, 'name': 'iPad', 'state': 'Booted', 'isAvailable': True},
        ]}
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert kwargs['shell'] is False
        if argv == ['xcrun', 'simctl', 'list', '-j', 'devices']:
            return SimpleNamespace(returncode=0, stdout=json.dumps({'devices': self.devices}), stderr='')
        self.calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='', stderr='')


class SimulatorCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = pathlib.Path(self.temp.name)
        for udid, size in ((GOOD, 5), (GONE, 7)):
            folder = home / 'Library/Developer/CoreSimulator/Devices' / udid
            folder.mkdir(parents=True)
            (folder / 'data').write_bytes(b'x' * size)
        self.env = {'HOME': str(home)}
        self.fake = FakeSimctl()
        self.kw = {'platform': 'macos', 'env': self.env, 'run': self.fake}

    def tearDown(self):
        self.temp.cleanup()

    def test_actions_are_fixed_and_unselected(self):
        listed = simulators.actions()
        self.assertEqual({a['id'] for a in listed}, set(simulators.ACTIONS))
        self.assertTrue(all(not a['defaultSelected'] for a in listed))

    def test_delete_unavailable_previews_then_runs_fixed_argv(self):
        plan = simulators.preview(ROOT, 'simulators.delete-unavailable', **self.kw)
        self.assertEqual(plan.device_ids, (GONE,))
        self.assertEqual(plan.bytes, 7)
        self.assertEqual(plan.argv, ('xcrun', 'simctl', 'delete', 'unavailable'))
        result = simulators.execute(ROOT, plan, **self.kw)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['bytesFreed'], 7)
        self.assertEqual(self.fake.calls, [['xcrun', 'simctl', 'delete', 'unavailable']])

    def test_erase_selected_shutdown_device(self):
        plan = simulators.preview(ROOT, 'simulators.erase-devices', [GOOD], **self.kw)
        simulators.execute(ROOT, plan, **self.kw)
        self.assertEqual(self.fake.calls, [['xcrun', 'simctl', 'erase', GOOD]])

    def test_booted_device_is_refused(self):
        with self.assertRaisesRegex(simulators.SimulatorError, 'Shut down iPad'):
            simulators.preview(ROOT, 'simulators.delete-devices', [BOOTED], **self.kw)

    def test_invalid_selection_is_refused(self):
        for ids in (None, [], ['../x'], [GOOD, GOOD], ['D1B2C3D4-1111-2222-3333-444455556666']):
            with self.assertRaises(simulators.SimulatorError):
                simulators.preview(ROOT, 'simulators.delete-devices', ids, **self.kw)
        with self.assertRaises(simulators.SimulatorError):
            simulators.preview(ROOT, 'simulators.delete-unavailable', [GOOD], **self.kw)
        with self.assertRaises(simulators.SimulatorError):
            simulators.preview(ROOT, 'simulators.rm-rf', **self.kw)

    def test_changed_devices_never_run(self):
        plan = simulators.preview(ROOT, 'simulators.delete-devices', [GOOD], **self.kw)
        self.fake.devices['com.apple.CoreSimulator.SimRuntime.iOS-18-0'][0]['state'] = 'Booted'
        with self.assertRaises(simulators.SimulatorError):
            simulators.execute(ROOT, plan, **self.kw)
        self.assertEqual(self.fake.calls, [])

    def test_expired_preview_never_runs(self):
        plan = simulators.preview(ROOT, 'simulators.delete-unavailable', clock=lambda: 0, **self.kw)
        with self.assertRaisesRegex(simulators.SimulatorError, 'expired'):
            simulators.execute(ROOT, plan, clock=lambda: 601, **self.kw)
        self.assertEqual(self.fake.calls, [])

    def test_not_macos(self):
        with self.assertRaises(simulators.SimulatorError):
            simulators.preview(ROOT, 'simulators.delete-unavailable', platform='linux', env=self.env, run=self.fake)


if __name__ == '__main__':
    unittest.main()
