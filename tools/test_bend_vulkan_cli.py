"""Focused subprocess tests for the portable CPU-only CLI.

The CLI is exercised as a subprocess from unrelated working directories. Fake
`cargo`, `bun` and `clang` executables are placed on a private PATH so the
tests remain fast and hermetic; the real Python check scripts still run.
"""
import json
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


def write_recording_fake(directory: Path, name: str, marker: Path) -> None:
    script = directory / name
    script.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('ran')\n"
        "sys.exit(0)\n"
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
        self.assertIn("doctor", result.stdout)

    def test_check_help(self):
        result = self.run_cli(["check", "--help"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--f32", result.stdout)

    def test_doctor_help(self):
        result = self.run_cli(["doctor", "--help"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--json", result.stdout)

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

    def test_check_accepts_finite_positive_timeout(self):
        write_fake(self.bindir, "cargo", "FAKE_CARGO_EXIT")
        result = self.run_cli(["check", "--timeout", "5"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_rejects_nonpositive_timeout(self):
        for value in ("0", "-1", "-600"):
            with self.subTest(value=value):
                result = self.run_cli(["check", "--timeout", value], self.env())
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--timeout", result.stderr)

    def test_check_rejects_nonfinite_timeout(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                result = self.run_cli(["check", f"--timeout={value}"], self.env())
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--timeout", result.stderr)
                self.assertIn("finite", result.stderr)

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

    def _load_doctor_json(self, result):
        payload = json.loads(result.stdout)
        self.assertEqual(payload["cpu_only"], True)
        self.assertEqual(payload["gpu_dispatches"], 0)
        self.assertIn("tools", payload)
        self.assertEqual(
            set(payload["tools"]), {"cargo", "bun", "clang"}, result.stdout
        )
        return payload

    def test_doctor_json_all_present(self):
        for name in ("cargo", "bun", "clang"):
            write_fake(self.bindir, name, f"FAKE_{name.upper()}_EXIT")
        result = self.run_cli(["doctor", "--json"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self._load_doctor_json(result)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["missing"], [])
        for name in payload["tools"]:
            self.assertTrue(payload["tools"][name]["available"])
            self.assertIsInstance(payload["tools"][name]["path"], str)

    def test_doctor_json_valid_when_all_missing(self):
        result = self.run_cli(["doctor", "--json"], self.env())
        self.assertNotEqual(result.returncode, 0)
        payload = self._load_doctor_json(result)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(set(payload["missing"]), {"cargo", "bun", "clang"})
        for name in payload["tools"]:
            self.assertFalse(payload["tools"][name]["available"])
            self.assertIsNone(payload["tools"][name]["path"])

    def test_doctor_json_valid_when_partially_missing(self):
        write_fake(self.bindir, "cargo", "FAKE_CARGO_EXIT")
        result = self.run_cli(["doctor", "--json"], self.env())
        self.assertNotEqual(result.returncode, 0)
        payload = self._load_doctor_json(result)
        self.assertEqual(payload["missing"], ["bun", "clang"])
        self.assertTrue(payload["tools"]["cargo"]["available"])
        self.assertFalse(payload["tools"]["bun"]["available"])
        self.assertIsNone(payload["tools"]["clang"]["path"])

    def test_doctor_human_reports_hints_and_scope_when_missing(self):
        result = self.run_cli(["doctor"], self.env())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MISSING", result.stdout)
        self.assertIn("rustup.rs", result.stdout)
        self.assertIn("bun.sh", result.stdout)
        self.assertIn("apt-get install clang", result.stdout)
        self.assertIn("Vulkan is never dispatched", result.stdout)
        self.assertIn("FAILED", result.stderr)

    def test_doctor_human_succeeds_when_all_present(self):
        for name in ("cargo", "bun", "clang"):
            write_fake(self.bindir, name, f"FAKE_{name.upper()}_EXIT")
        result = self.run_cli(["doctor"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SUCCESS", result.stdout)
        self.assertNotIn("MISSING", result.stdout)

    def test_doctor_never_executes_tools(self):
        marker = self.tmp / "executed"
        for name in ("cargo", "bun", "clang"):
            write_recording_fake(self.bindir, name, marker)
        result = self.run_cli(["doctor", "--json"], self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), "doctor executed a compiler tool")
        self._load_doctor_json(result)


if __name__ == "__main__":
    unittest.main()
