"""CLN-14 shred policy, overwrite passes and honest failures on temp files."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_lab import clean, settings, shred  # noqa: E402

class ShredTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temp.name)
        self.env = {'HOME': str(self.home), 'OSLAB_CLEANUP_STATE': str(self.home / 'private-state')}
        self.cache = self.home / 'Library/Caches/demo'
        self.cache.mkdir(parents=True)
        self.entry = {'id':'system.demo','name':'demo','category':'system','risk':'low',
                      'hint':'cache','impact':'rebuild','defaultSelected':False,'needsPrivilege':False,
                      'owningProcesses':[],'detector':'paths','paths':{'macos':['~/Library/Caches/demo']}}

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return clean.build_plan(None, ['system.demo'], mode='shred', env=self.env,
                                platform='macos', catalog_entries=[self.entry], names=())

    def test_off_is_default_and_refuses_plan(self):
        self.assertEqual(settings.read(env=self.env, platform='macos')['shredPolicy'], 'off')
        (self.cache / 'file').write_bytes(b'secret')
        with self.assertRaises(clean.PlanError):
            self.build()
        self.assertTrue((self.cache / 'file').exists())

    def test_one_pass_nested_directory_removes_and_counts(self):
        settings.update('one-pass', env=self.env, platform='macos')
        nested = self.cache / 'nested'
        nested.mkdir()
        (nested / 'file').write_bytes(b'secret')
        plan = self.build()
        self.assertEqual(plan.payload['shredPolicy'], 'one-pass')
        self.assertIn('cannot guarantee', plan.payload['shredLimitation'])
        result = clean.execute_plan(plan, clean.verify_plan(plan), env=self.env, platform='macos')
        self.assertEqual(result['results'][0]['status'], 'shredded')
        self.assertEqual(result['totals']['bytes'], 6)
        self.assertEqual(result['totals']['shredded'], 1)
        self.assertFalse(self.cache.exists())

    def test_policy_change_stales_confirmed_plan(self):
        settings.update('one-pass', env=self.env, platform='macos')
        target = self.cache / 'file'
        target.write_bytes(b'secret')
        plan = self.build()
        settings.update('off', env=self.env, platform='macos')
        with self.assertRaisesRegex(clean.PlanError, 'policy changed'):
            clean.execute_plan(plan, clean.verify_plan(plan), env=self.env, platform='macos')
        self.assertEqual(target.read_bytes(), b'secret')

    def test_three_pass_patterns(self):
        path = self.cache / 'file'
        path.write_bytes(b'abc')
        seen = []
        real_write = shred._write_all
        def record(fd, data):
            seen.append(bytes(data))
            return real_write(fd, data)
        with patch.object(shred, '_write_all', record):
            shred._overwrite(str(path), (0, 255, 'random'), random_bytes=lambda n: b'B' * n)
        self.assertEqual(seen, [b'\x00'*3, b'\xff'*3, b'B'*3])
        self.assertEqual(path.read_bytes(), b'B'*3)

    def test_hardlink_and_symlink_are_not_claimed_shredded(self):
        settings.update('one-pass', env=self.env, platform='macos')
        target = self.cache / 'file'
        target.write_bytes(b'keep')
        os.link(target, self.cache / 'second')
        plan = self.build()
        result = clean.execute_plan(plan, clean.verify_plan(plan), env=self.env, platform='macos')
        self.assertEqual(result['results'][0]['status'], 'failed')
        self.assertEqual(result['totals']['bytes'], 0)
        self.assertTrue(target.exists())
        (self.cache / 'link').symlink_to(target)
        plan = self.build()
        self.assertEqual(plan.payload['items'][0]['code'], 'shred-unsupported')

if __name__ == '__main__':
    unittest.main()
