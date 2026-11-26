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


RT_OLD = 'D1D2D3D4-1111-2222-3333-444455556666'
RT_XCODE = 'E1E2E3E4-1111-2222-3333-444455556666'


class FakeSimctl:
    def __init__(self):
        self.runtimes = {
            RT_OLD: {'identifier': RT_OLD, 'version': '15.0', 'build': '19A339', 'deletable': True, 'state': 'Ready',
                     'runtimeIdentifier': 'com.apple.CoreSimulator.SimRuntime.iOS-15-0', 'sizeBytes': 6_000_000_000,
                     'kind': 'Disk Image'},
            RT_XCODE: {'identifier': RT_XCODE, 'version': '18.0', 'deletable': False, 'state': 'Ready',
                       'runtimeIdentifier': 'com.apple.CoreSimulator.SimRuntime.iOS-18-0', 'sizeBytes': 8_000_000_000},
        }
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
        if argv == ['xcrun', 'simctl', 'runtime', 'list', '-j']:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.runtimes), stderr='')
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

    def test_runtime_list_and_single_runtime_delete(self):
        listed = simulators.runtimes(platform='macos', run=self.fake)
        self.assertEqual({r['name'] for r in listed['runtimes']}, {'iOS 15.0', 'iOS 18.0'})
        self.fake.devices['com.apple.CoreSimulator.SimRuntime.iOS-15-0'] = [
            {'udid': 'F1B2C3D4-1111-2222-3333-444455556666', 'name': 'Old phone', 'state': 'Shutdown', 'isAvailable': True},
            {'udid': 'F2B2C3D4-1111-2222-3333-444455556666', 'name': 'Old pad', 'state': 'Shutdown', 'isAvailable': True}]
        plan = simulators.preview(ROOT, 'simulators.delete-runtime', [RT_OLD], **self.kw)
        self.assertEqual(plan.argv, ('xcrun', 'simctl', 'runtime', 'delete', RT_OLD))
        self.assertEqual(plan.bytes, 6_000_000_000)
        self.assertEqual(plan.devices[0]['devicesUsing'], 2)
        simulators.execute(ROOT, plan, **self.kw)
        self.assertEqual(self.fake.calls, [['xcrun', 'simctl', 'runtime', 'delete', RT_OLD]])

    def test_runtime_list_accepts_runtimes_array(self):
        payload = {'runtimes': [self.fake.runtimes[RT_OLD]]}

        def run(argv, **kwargs):
            self.assertEqual(argv, ['xcrun', 'simctl', 'runtime', 'list', '-j'])
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')

        listed = simulators.runtimes(platform='macos', run=run)
        self.assertEqual([r['id'] for r in listed['runtimes']], [RT_OLD])

    def test_runtime_list_skips_coresimulator_ids(self):
        payload = {'runtimes': [{'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-15-0',
                                 'runtimeIdentifier': 'com.apple.CoreSimulator.SimRuntime.iOS-15-0',
                                 'version': '15.0', 'deletable': True}]}

        def run(argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')

        listed = simulators.runtimes(platform='macos', run=run)
        self.assertEqual(listed['runtimes'], [])

    def test_runtime_delete_refuses_when_devices_unavailable(self):
        def run(argv, **kwargs):
            if argv == ['xcrun', 'simctl', 'runtime', 'list', '-j']:
                return SimpleNamespace(returncode=0, stdout=json.dumps(self.fake.runtimes), stderr='')
            if argv == ['xcrun', 'simctl', 'list', '-j', 'devices']:
                return SimpleNamespace(returncode=1, stdout='', stderr='simctl failed')
            raise AssertionError(argv)

        with self.assertRaisesRegex(simulators.SimulatorError, 'Cannot check which simulators use this runtime'):
            simulators.preview(ROOT, 'simulators.delete-runtime', [RT_OLD], platform='macos', env=self.env, run=run)

    def test_runtime_delete_refuses_missing_runtime_identifier(self):
        self.fake.runtimes[RT_OLD].pop('runtimeIdentifier')
        with self.assertRaisesRegex(simulators.SimulatorError, 'no runtime identifier'):
            simulators.preview(ROOT, 'simulators.delete-runtime', [RT_OLD], **self.kw)

    def test_runtime_refusals(self):
        with self.assertRaisesRegex(simulators.SimulatorError, 'managed by Xcode'):
            simulators.preview(ROOT, 'simulators.delete-runtime', [RT_XCODE], **self.kw)
        for ids in (None, [], [RT_OLD, RT_XCODE], ['nope']):
            with self.assertRaises(simulators.SimulatorError):
                simulators.preview(ROOT, 'simulators.delete-runtime', ids, **self.kw)
        self.fake.devices['com.apple.CoreSimulator.SimRuntime.iOS-15-0'] = [
            {'udid': 'F1B2C3D4-1111-2222-3333-444455556666', 'name': 'Old phone', 'state': 'Booted', 'isAvailable': True}]
        with self.assertRaisesRegex(simulators.SimulatorError, 'Shut down Old phone'):
            simulators.preview(ROOT, 'simulators.delete-runtime', [RT_OLD], **self.kw)

    def test_changed_runtime_never_runs(self):
        plan = simulators.preview(ROOT, 'simulators.delete-runtime', [RT_OLD], **self.kw)
        self.fake.runtimes[RT_OLD]['sizeBytes'] = 1
        with self.assertRaises(simulators.SimulatorError):
            simulators.execute(ROOT, plan, **self.kw)
        self.assertEqual(self.fake.calls, [])

    def test_not_macos(self):
        with self.assertRaises(simulators.SimulatorError):
            simulators.preview(ROOT, 'simulators.delete-unavailable', platform='linux', env=self.env, run=self.fake)


if __name__ == '__main__':
    unittest.main()
