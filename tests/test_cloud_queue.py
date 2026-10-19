"""Reproduce queued GitHub runs against a real local Git remote."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CloudQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.git(self.root, 'init', '--bare', str(self.remote))
        self.writer = self.clone('writer')
        self.git(self.writer, 'checkout', '-b', 'main')
        self.write_commit(self.writer, 'source.py', 'source v1')
        self.git(self.writer, 'push', '-u', 'origin', 'main')
        self.trigger_sha = self.git(self.writer, 'rev-parse', 'HEAD').stdout.strip()

    def tearDown(self):
        # Git objects can be read-only on Windows.
        import os
        import stat
        import shutil
        def retry(fn, path, exc):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.root, onerror=retry)
        self.temp.cleanup()

    def git(self, cwd, *args, check=True):
        return subprocess.run(['git', *args], cwd=cwd, check=check,
                              capture_output=True, text=True)

    def clone(self, name):
        target = self.root / name
        self.git(self.root, 'clone', str(self.remote), str(target))
        self.git(target, 'config', 'user.name', 'queue regression')
        self.git(target, 'config', 'user.email', 'queue@example.invalid')
        return target

    def write_commit(self, repo, name, content):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        self.git(repo, 'add', name)
        self.git(repo, 'commit', '-m', content)

    def advance_main(self):
        self.write_commit(self.writer, 'site/report.txt', 'preceding verified report')
        self.git(self.writer, 'push', 'origin', 'HEAD:main')

    def test_old_event_checkout_reproduces_rejected_push(self):
        self.advance_main()
        queued = self.clone('old-event')
        self.git(queued, 'checkout', self.trigger_sha)
        self.write_commit(queued, 'site/report.txt', 'queued report')
        result = self.git(queued, 'push', 'origin', 'HEAD:main', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rejected', result.stderr.lower())

    def test_configured_checkout_resolves_latest_main_after_wait(self):
        workflow = (ROOT / '.github/workflows/tiantianle-cloud-auto-update.yml').read_text(encoding='utf-8')
        checkout = workflow.split('uses: actions/checkout@', 1)[1].split('- uses:', 1)[0]
        match = re.search(r'^\s+ref:\s*(\S+)\s*$', checkout, re.MULTILINE)
        self.assertIsNotNone(match, 'Queued runs must explicitly resolve the current main')
        self.assertEqual(match.group(1), 'main')
        self.advance_main()
        queued = self.clone('latest-main')
        self.git(queued, 'checkout', match.group(1))
        self.assertNotEqual(self.git(queued, 'rev-parse', 'HEAD').stdout.strip(), self.trigger_sha)
        self.write_commit(queued, 'site/report.txt', 'queued verified report')
        self.git(queued, 'push', 'origin', 'HEAD:main')
        reader = self.clone('reader')
        self.git(reader, 'checkout', 'main')
        self.assertEqual((reader / 'site/report.txt').read_text(), 'queued verified report')
        self.assertEqual((reader / 'source.py').read_text(), 'source v1')

    def test_source_change_during_calculation_is_detected(self):
        queued = self.clone('calculating')
        self.git(queued, 'checkout', 'main')
        self.write_commit(self.writer, 'source.py', 'source v2')
        self.git(self.writer, 'push', 'origin', 'HEAD:main')
        self.git(queued, 'fetch', 'origin', 'main')
        check = self.git(queued, 'merge-base', '--is-ancestor', 'origin/main', 'HEAD', check=False)
        self.assertNotEqual(check.returncode, 0)
        self.git(self.writer, 'fetch', 'origin', 'main')
        self.assertEqual(self.git(self.writer, 'show', 'origin/main:source.py').stdout.strip(), 'source v2')


if __name__ == '__main__':
    unittest.main()
