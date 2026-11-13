"""CLN-17 ignore rules are enforced in scans and confirmed plans."""
import os
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cleanup_lab import clean, rules, scan  # noqa: E402

class RuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temp.name)
        self.env = {'HOME': str(self.home), 'OSLAB_CLEANUP_STATE': str(self.home / 'state')}
        self.cache = self.home / 'Library/Caches/app'
        self.cache.mkdir(parents=True)
        (self.cache / 'keep.bin').write_bytes(b'12345')
        (self.cache / 'secret.log').write_bytes(b'abcdef')
        self.entry = {'id':'system.demo','name':'demo','category':'system','risk':'low',
                      'hint':'cache','impact':'rebuild','defaultSelected':False,'needsPrivilege':False,
                      'owningProcesses':[],'detector':'paths','paths':{'macos':['~/Library/Caches/app']}}

    def tearDown(self):
        self.temp.cleanup()

    def test_crud_store_and_private_mode(self):
        self.assertEqual(rules.read(env=self.env, platform='macos')['rules'], [])
        item = rules.add('extension', '.log', env=self.env, platform='macos')
        self.assertEqual(len(rules.read(env=self.env, platform='macos')['rules']), 1)
        self.assertEqual(os.stat(self.home / 'state/ignore-rules.json').st_mode & 0o777, 0o600)
        rules.update(item['id'], enabled=False, env=self.env, platform='macos')
        self.assertFalse(rules.matcher(rules.read(env=self.env, platform='macos')).matches(self.cache / 'secret.log'))
        rules.update(item['id'], kind='glob', value='*.log', enabled=True, env=self.env, platform='macos')
        self.assertTrue(rules.matcher(rules.read(env=self.env, platform='macos')).matches(self.cache / 'secret.log'))
        rules.delete(item['id'], env=self.env, platform='macos')
        self.assertEqual(rules.read(env=self.env, platform='macos')['rules'], [])

    def test_ignored_descendant_not_scanned_or_planned(self):
        rules.add('extension', '.log', env=self.env, platform='macos')
        result = scan.scan_catalog(None, ['system.demo'], env=self.env, platform='macos', catalog_entries=[self.entry])
        path = result['entries'][0]['paths'][0]
        self.assertEqual(path['sizeBytes'], 5)
        self.assertIn(str(self.cache / 'secret.log'), path['ignored'])
        plan = clean.build_plan(None, ['system.demo'], env=self.env, platform='macos',
                                catalog_entries=[self.entry], names=())
        self.assertEqual(plan.payload['items'][0]['code'], 'ignored')
        self.assertEqual(plan.payload['totals']['ready'], 0)
        self.assertTrue((self.cache / 'secret.log').exists())

    def test_rule_change_expires_plan_before_clean(self):
        plan = clean.build_plan(None, ['system.demo'], env=self.env, platform='macos',
                                catalog_entries=[self.entry], names=())
        self.assertEqual(plan.payload['items'][0]['status'], 'ready')
        rules.add('path', str(self.cache / 'secret.log'), env=self.env, platform='macos')
        with self.assertRaisesRegex(clean.PlanError, 'Ignore rules changed'):
            clean.verify_plan(plan)

    def test_invalid_rules_are_refused(self):
        for kind,value in [('extension','log'),('path','relative'),('glob',' x '),('extension','.-bad')]:
            with self.subTest(kind=kind,value=value), self.assertRaises(rules.RulesError):
                rules.add(kind,value,env=self.env,platform='macos')

if __name__ == '__main__':
    unittest.main()
