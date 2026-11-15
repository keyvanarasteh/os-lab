"""PENT-05 hardening audit + crash triage tests.

Runs the offline bash suite (fake readelf and fake crash target from
fixtures/pent05, so only bash and coreutils are needed) and parses the
--json output of both tools with json.loads, so malformed JSON fails here
even when the bash suite cannot find python3 or jq.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SUITE = HERE / 'pent05_test.sh'
SCRIPTS = HERE.parent / 'scripts'
FIX = HERE / 'fixtures' / 'pent05'
AUDIT = SCRIPTS / 'pent-05-hardening-audit.sh'
TRIAGE = SCRIPTS / 'pent-05-afl-triage.sh'

HAVE_BASH = shutil.which('bash') is not None


def run(args, env=None):
    full_env = dict(os.environ)
    full_env.update(env or {})
    return subprocess.run(['bash', *map(str, args)], capture_output=True, text=True,
                          encoding='utf-8', timeout=300, env=full_env)


@unittest.skipUnless(HAVE_BASH, 'bash is required')
class Pent05Suite(unittest.TestCase):
    def test_offline_suite(self):
        proc = run([SUITE])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(' 0 başarısız', proc.stdout)


@unittest.skipUnless(HAVE_BASH, 'bash is required')
class Pent05Json(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {'PENT05_READELF': str(FIX / 'fake-readelf.sh'),
                    'PENT05_ASLR_FILE': str(self.tmp / 'aslr')}
        (self.tmp / 'aslr').write_text('2\n')

    def test_audit_json_is_valid(self):
        for name in ('hardened', 'weak', 'lib', 'staticpie'):
            (self.tmp / name).write_bytes(b'')
        odd = self.tmp / 'a|b\tc"d'
        odd.write_bytes(b'')
        files = [self.tmp / n for n in ('hardened', 'weak', 'lib', 'staticpie')] + [odd, self.tmp / 'missing']
        proc = run([AUDIT, '--json', *files], self.env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        data = json.loads(proc.stdout)
        by_file = {Path(b['file']).name: b for b in data['binaries']}
        self.assertEqual(by_file['hardened']['verdict'], 'hardened')
        self.assertEqual(by_file['weak']['missing'], ['nx', 'pie', 'canary', 'relro'])
        self.assertEqual(by_file['lib']['pie'], 'dso')
        self.assertEqual(by_file['staticpie']['pie'], 'yes')
        self.assertEqual(by_file[odd.name]['verdict'], 'error')
        self.assertEqual(by_file['missing']['verdict'], 'error')
        self.assertEqual((data['weak'], data['errors']), (1, 2))

    def test_triage_json_is_valid(self):
        crashes = self.tmp / 'crashes'
        crashes.mkdir()
        (crashes / 'id-000').write_text('SEGV')
        (crashes / 'id-001').write_text('ASANCPP')
        (crashes / 'id-002').write_text('tamam')
        (crashes / 'a|b\tc').write_text('SEGV')
        proc = run([TRIAGE, 'triage', '--json', '--timeout', '2', crashes, '--',
                    'bash', FIX / 'fake-target.sh', '@@'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual((data['inputs'], data['buckets'], data['unique_crashes']), (4, 3, 2))
        kinds = {g['kind']: g for g in data['groups']}
        self.assertEqual(kinds['signal:SIGSEGV']['count'], 2)
        self.assertEqual(kinds['asan:heap-buffer-overflow']['frames'],
                         'operator new(unsigned long)<Kutu::doldur(char const*, int)')
        self.assertIn('no-crash', kinds)

    def test_fuzz_json_stdout_is_clean_without_afl(self):
        proc = run([TRIAGE, 'fuzz', '--json', '--seconds', '1'], {'PENT05_AFL_FUZZ': '/nonexistent/afl-fuzz'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '')
        self.assertIn('[skip]', proc.stderr)


if __name__ == '__main__':
    unittest.main()
