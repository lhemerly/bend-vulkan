"""Public CLI contracts: build ownership, relocation, selection and diagnostics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT/'bend-vulkan'


class GeneralCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='bend-cli-check-')
        cls.directory = Path(cls.temporary.name)
        cls.source = cls.directory/'source with spaces.bend'
        cls.source.write_text('import Base\n\ndef main() -> U32:\n  42\n')
        cls.bundle = cls.directory/'build with spaces'
        p = cls.invoke('build', cls.source, '-o', cls.bundle, '--backend', 'cpu')
        if p.returncode:
            raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def invoke(*args):
        return subprocess.run([str(CLI), *map(str, args)], capture_output=True, text=True, timeout=30,
                              env={**os.environ, 'BEND_FORK_TRANSPORT': 'unrelated-legacy-config'})

    def test_cpu_build_runs_without_legacy_transport(self):
        p = self.invoke('run', self.bundle)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, '42\n', ''))

    def test_existing_output_is_preserved(self):
        before = (self.bundle/'build.json').read_bytes()
        p = self.invoke('build', self.source, '-o', self.bundle, '--backend', 'cpu')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('new directory', p.stderr)
        self.assertEqual((self.bundle/'build.json').read_bytes(), before)

    def test_relocated_bundle(self):
        moved = self.directory/'relocated build'
        shutil.copytree(self.bundle, moved)
        p = self.invoke('run', moved)
        self.assertEqual((p.returncode, p.stdout), (0, '42\n'))

    def test_modified_artifact_is_rejected_before_execution(self):
        changed = self.directory/'changed build'
        shutil.copytree(self.bundle, changed)
        with (changed/'program').open('ab') as stream:
            stream.write(b'changed')
        p = self.invoke('run', changed)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, '')
        self.assertIn('build artifact changed: program', p.stderr)

    def test_cpu_build_cannot_claim_vulkan(self):
        p = self.invoke('run', self.bundle, '--backend', 'vulkan')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, '')
        self.assertIn('no Vulkan module', p.stderr)

    def test_checker_errors_are_concise(self):
        source = self.directory/'invalid.bend'
        source.write_text('import Base\n\ndef main() -> U32:\n  True{}\n')
        p = self.invoke('build', source, '-o', self.directory/'invalid build', '--backend', 'cpu')
        self.assertNotEqual(p.returncode, 0)
        self.assertLess(len(p.stderr), 10000)
        self.assertFalse((self.directory/'invalid build/build.json').exists())

    def test_manifest_records_cpu_backend(self):
        manifest = json.loads((self.bundle/'build.json').read_text())
        self.assertEqual(manifest['backend'], 'cpu')
        self.assertNotIn('program.gpu', manifest['files'])


if __name__ == '__main__':
    unittest.main()
