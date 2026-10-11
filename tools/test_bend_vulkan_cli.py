"""Focused subprocess tests for the portable CPU-only CLI.

The CLI is exercised as a subprocess from unrelated working directories. Fake
`cargo`, `bun` and `clang` executables are placed on a private PATH so the
tests remain fast and hermetic; the real Python check scripts still run.
"""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).with_name("bend_vulkan.py").resolve()


def write_fake(directory: Path, name: str, exit_env: str) -> None:
    script = directory / name
    script.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        f"sys.exit(int(os.environ.get({exit_env!r}, '0')))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="bend-cli-test-")
        self.tmp = Path(self._tmp.name)
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        self.cwd = self.tmp / "unrelated"
        self.cwd.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, path=None, **extra):
        base = {"PATH": os.pathsep.join([str(self.bindir)] + ([path] if path else []))}
        env = {**base, **extra}
        return env

    def run_cli(self, args, env):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(self.cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_top_level_help(self):
        result = self.run_cli(["--help"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("check", result.stdout)

    def test_check_help(self):
        result = self.run_cli(["check", "--help"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--f32", result.stdout)

    def test_invalid_command_fails(self):
        result = self.run_cli(["nope"], self.env())
        self.assertNotEqual(result.returncode, 0)

    def test_check_runs_offline_from_unrelated_cwd(self):
        write_fake(self.bindir, "cargo", "FAKE_CARGO_EXIT")
        result = self.run_cli(["check"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cargo test --offline", result.stdout)
        self.assertIn("cargo clippy --offline --all-targets -- -D warnings", result.stdout)
        self.assertIn("test_emit_u32_segment.py", result.stdout)
        self.assertIn("no Vulkan dispatch", result.stdout)

    def test_check_stops_immediately_on_failure(self):
        write_fake(self.bindir, "cargo", "FAKE_CARGO_EXIT")
        result = self.run_cli(["check"], self.env(FAKE_CARGO_EXIT="3"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stderr)
        self.assertNotIn("cargo clippy", result.stdout)

    def test_missing_cargo_fails(self):
        result = self.run_cli(["check"], self.env())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cargo", result.stderr)

    def test_f32_missing_bun_fails(self):
        write_fake(self.bindir, "cargo", "FAKE_CARGO_EXIT")
        write_fake(self.bindir, "clang", "FAKE_CLANG_EXIT")
        result = self.run_cli(["check", "--f32"], self.env())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bun", result.stderr)

    def test_f32_cleans_temporary_output_on_failure(self):
        write_fake(self.bindir, "cargo", "FAKE_CARGO_EXIT")
        write_fake(self.bindir, "clang", "FAKE_CLANG_EXIT")
        write_fake(self.bindir, "bun", "FAKE_BUN_EXIT")
        result = self.run_cli(["check", "--f32"], self.env(FAKE_BUN_EXIT="1"))
        self.assertNotEqual(result.returncode, 0)
        marker = "f32 temporary output: "
        line = next(l for l in result.stdout.splitlines() if marker in l)
        out = Path(line.split(marker, 1)[1].strip())
        self.assertFalse(out.exists(), f"temporary output survived: {out}")
        self.assertIn("cleaned up temporary output", result.stdout)


if __name__ == "__main__":
    unittest.main()
