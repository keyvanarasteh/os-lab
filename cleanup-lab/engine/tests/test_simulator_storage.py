"""CLS-02 simulator storage: saved destination, location states and suggestions."""
import os
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_lab import simulator_storage as storage  # noqa: E402
ROOT = str(pathlib.Path(__file__).resolve().parents[3])
GIB = 1024 ** 3


class SimulatorStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.temp.name)
        self.home = base / 'home'
        self.devices = self.home / 'Library/Developer/CoreSimulator/Devices'
        self.devices.mkdir(parents=True)
        self.external = base / 'Volumes' / 'Fast'
        self.external.mkdir(parents=True)
        self.env = {'HOME': str(self.home), 'OSLAB_CLEANUP_STATE': str(base / 'state')}
        self.rows = [
            {'mountPoint': '/', 'kind': 'root', 'isHome': True, 'freeBytes': 5 * GIB, 'totalBytes': 500 * GIB},
            {'mountPoint': str(self.external), 'name': 'Fast', 'kind': 'removable', 'isHome': False,
             'freeBytes': 900 * GIB, 'totalBytes': 1000 * GIB},
            {'mountPoint': '/net', 'kind': 'unknown', 'isHome': False, 'freeBytes': 1, 'totalBytes': 2},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def status(self):
        return storage.status(ROOT, platform='macos', env=self.env, inventory={'volumes': self.rows})

    def test_defaults_offer_other_volumes_only(self):
        report = self.status()
        self.assertEqual(report['state'], 'local')
        self.assertEqual([d['mountPoint'] for d in report['destinations']], [str(self.external)])
        self.assertIsNone(report['suggestion']['action'])

    def test_low_system_disk_suggests_move_to_saved_destination(self):
        storage.save({'destination': str(self.external)}, env=self.env, platform='macos',
                     destinations=[str(self.external)])
        report = self.status()
        self.assertEqual(report['suggestion']['action'], 'move')
        title, message = storage.notification(report)
        self.assertIn(str(self.external), message)
        self.rows[0]['freeBytes'] = 50 * GIB
        self.assertIsNone(self.status()['suggestion']['action'])

    def test_suggestions_can_be_turned_off(self):
        storage.save({'destination': str(self.external), 'suggest': False}, env=self.env, platform='macos')
        self.assertIsNone(self.status()['suggestion']['action'])

    def test_linked_and_disconnected_states(self):
        store = self.external / 'oslab-caches' / storage.ENTRY_ID
        store.mkdir(parents=True)
        self.devices.rmdir()
        self.devices.symlink_to(store)
        report = self.status()
        self.assertEqual(report['state'], 'linked')
        self.assertEqual(report['volume']['mountPoint'], str(self.external))
        store.rmdir()
        report = self.status()
        self.assertEqual(report['state'], 'disk-missing')
        self.assertEqual(report['suggestion']['action'], 'reconnect')

    def test_parent_folder_link_counts_as_another_disk(self):
        moved = self.external / 'DeveloperData' / 'CoreSimulator'
        (moved / 'Devices').mkdir(parents=True)
        parent = self.home / 'Library/Developer/CoreSimulator'
        self.devices.rmdir()
        parent.rmdir()
        parent.symlink_to(moved)
        report = self.status()
        self.assertEqual(report['state'], 'linked')
        self.assertEqual(report['volume']['mountPoint'], str(self.external))
        (moved / 'Devices').rmdir()
        moved.rmdir()
        report = self.status()
        self.assertEqual(report['state'], 'disk-missing')
        self.assertEqual(report['suggestion']['action'], 'reconnect')

    def test_config_validation(self):
        for bad in ({'destination': 'relative'}, {'floorBytes': 1}, {'suggest': 'yes'}, {'extra': 1}, []):
            with self.assertRaises(storage.StorageConfigError):
                storage.validate_config(bad)
        with self.assertRaises(storage.StorageConfigError):
            storage.save({'destination': '/Volumes/Other'}, env=self.env, platform='macos', destinations=['/x'])

    def test_corrupt_store_falls_back_to_defaults(self):
        path = pathlib.Path(self.env['OSLAB_CLEANUP_STATE']) / storage.STORE
        path.parent.mkdir(parents=True)
        path.write_text('{not json')
        loaded = storage.load(self.env, 'macos')
        self.assertEqual(loaded['config'], storage.default_config())
        self.assertTrue(loaded['configError'])

    def test_other_platforms(self):
        self.assertFalse(storage.status(ROOT, platform='linux', env=self.env, inventory={'volumes': []})['available'])


if __name__ == '__main__':
    unittest.main()
