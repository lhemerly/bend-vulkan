"""Public CLI contracts: build ownership, relocation, selection and diagnostics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
        cls.args_source = cls.directory/'args.bend'
        cls.args_source.write_text(
            'import Base\n\n'
            'def main() -> IO(Unit):\n'
            '  do IO<Unit>:\n'
            '    xs : List<String> <- IO.args()\n'
            '    IO.print(Nat.show(List.length(&1, String, xs)))\n')
        cls.args_bundle = cls.directory/'args build'
        p = cls.invoke('build', cls.args_source, '-o', cls.args_bundle,
                       '--backend', 'cpu')
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

    def test_runtime_flags_are_not_exposed_to_io_args(self):
        p = self.invoke('run', self.args_bundle)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, '1\n', ''))
        p = self.invoke('run', self.args_bundle, '--', 'one', 'two')
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, '3\n', ''))

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

    def test_cpu_build_cannot_request_staging(self):
        p = self.invoke('run', self.bundle, '--staging')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('--staging requires a Vulkan build', p.stderr)

    def test_checker_errors_are_concise_and_leave_no_output(self):
        source = self.directory/'invalid.bend'
        source.write_text('import Base\n\ndef main() -> U32:\n  True{}\n')
        output = self.directory/'invalid build'
        p = self.invoke('build', source, '-o', output, '--backend', 'cpu')
        self.assertNotEqual(p.returncode, 0)
        self.assertLess(len(p.stderr), 10000)
        self.assertFalse(output.exists(), 'a failed build must not leave a partial directory')
        self.assertEqual(list(output.parent.glob('.bend-vulkan-build-*')), [],
                         'a failed build must remove its private staging directory')

    def test_manifest_records_cpu_backend(self):
        manifest = json.loads((self.bundle/'build.json').read_text())
        self.assertEqual(manifest['backend'], 'cpu')
        self.assertNotIn('program.gpu', manifest['files'])

    def test_version_is_available_without_a_subcommand(self):
        p = self.invoke('--version')
        self.assertEqual(p.returncode, 0)
        self.assertRegex(p.stdout.strip(), r'^bend-vulkan \d+\.\d+\.\d+$')

    def test_cube_log_mismatch_is_rejected(self):
        p = self.invoke('run', self.bundle, '--cube-log', '3')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('--cube-log does not match', p.stderr)

    def test_doctor_json_reports_prerequisites_without_dispatch(self):
        p = self.invoke('doctor', '--cpu-only', '--json')
        self.assertEqual(p.returncode, 0, p.stderr)
        report = json.loads(p.stdout)
        self.assertEqual((report['command'], report['gpu_dispatches']), ('doctor', 0))
        self.assertTrue(report['ok'])
        self.assertEqual(set(report['tools']), {'bun', 'clang'})
        self.assertEqual(report['tools']['clang']['command'], os.environ.get('CC', 'clang'))

    def test_doctor_reports_missing_tools_without_executing_them(self):
        p = subprocess.run([sys.executable, str(CLI), 'doctor', '--json'],
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ, 'PATH': '', 'CC': 'clang'})
        self.assertEqual(p.returncode, 1)
        report = json.loads(p.stdout)
        self.assertFalse(report['ok'])
        self.assertIn('bun', report['missing'])
        self.assertTrue(all(not item['available'] for item in report['tools'].values()))


if __name__ == '__main__':
    unittest.main()
