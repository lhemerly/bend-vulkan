#!/usr/bin/env python3
"""Portable CPU-only verification entry point for the bend-vulkan snapshot.

This is a Python 3 standard-library CLI. It runs the repository's existing CPU
checks sequentially from the repository root, independent of the caller's
working directory. It never dispatches Vulkan and never claims backend
completion: a passing run only reports that the CPU checks succeeded.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = 600.0

REQUIRED_TOOLS = ("cargo", "bun", "clang")
INSTALL_HINTS = {
    "cargo": "install Rust/Cargo from https://rustup.rs and ensure `cargo` is on PATH",
    "bun": "install Bun from https://bun.sh and ensure `bun` is on PATH",
    "clang": "install Clang (for example `apt-get install clang`) and ensure `clang` is on PATH",
}


class CheckError(RuntimeError):
    """A prerequisite or command failure that must stop the run immediately."""


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CheckError(f"missing prerequisite: {name!r} is not on PATH")
    return path


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise CheckError(f"missing prerequisite: {path} not found")
    return path


def run(argv, timeout: float):
    printable = " ".join(str(a) for a in argv)
    print(f"[cpu] $ {printable}", flush=True)
    try:
        return subprocess.run([str(a) for a in argv], cwd=str(ROOT), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CheckError(f"timeout after {timeout:g}s: {printable}") from exc


def run_checked(argv, timeout: float):
    result = run(argv, timeout)
    if result.returncode != 0:
        raise CheckError(f"command failed with exit code {result.returncode}: {argv[0]}")
    return result


def run_python(script: Path, extra, timeout: float):
    require_file(script)
    return run_checked([sys.executable, str(script), *extra], timeout)


def check_core(timeout: float) -> None:
    require_tool("cargo")
    print("[cpu] core checks: cargo test, warnings-denied clippy, emit-u32 tests", flush=True)
    run_checked(["cargo", "test", "--offline"], timeout)
    run_checked(["cargo", "clippy", "--offline", "--all-targets", "--", "-D", "warnings"], timeout)
    run_python(ROOT / "tools" / "test_emit_u32_segment.py", [], timeout)


def check_f32(timeout: float) -> None:
    for tool in ("bun", "clang"):
        require_tool(tool)
    script = require_file(ROOT / "fork" / "tests" / "check_f32_e2e.py")
    source = require_file(ROOT / "evidence" / "upstream" / "tests" / "run" / "gpu_trig.bend")

    # The existing script owns creation of its fresh output directory, so the
    # directory must not exist yet. The parent is removed in the finally block.
    base = Path(tempfile.mkdtemp(prefix="bend-vulkan-f32-"))
    out = base / "f32-e2e-output"
    print(f"[cpu] f32 temporary output: {out}", flush=True)
    try:
        run_python(script, [str(source), str(out)], timeout)
    finally:
        shutil.rmtree(base, ignore_errors=True)
        print(f"[cpu] cleaned up temporary output: {base}", flush=True)


def diagnose_tools() -> dict:
    # PATH-only lookup: never executes any compiler and never dispatches GPU work.
    tools = {}
    for name in REQUIRED_TOOLS:
        path = shutil.which(name)
        tools[name] = {"available": path is not None, "path": path}
    return tools


def doctor_payload() -> dict:
    tools = diagnose_tools()
    missing = [name for name in REQUIRED_TOOLS if not tools[name]["available"]]
    return {
        "command": "doctor",
        "cpu_only": True,
        "gpu_dispatches": 0,
        "ok": not missing,
        "missing": missing,
        "tools": tools,
    }


def doctor_json() -> int:
    payload = doctor_payload()
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return 0 if payload["ok"] else 1


def doctor_human() -> int:
    print(
        "[cpu] doctor: CPU-only prerequisite check; no compiler is executed and no GPU work is performed.",
        flush=True,
    )
    tools = diagnose_tools()
    missing = []
    for name in REQUIRED_TOOLS:
        info = tools[name]
        if info["available"]:
            print(f"[cpu] {name}: available at {info['path']}", flush=True)
        else:
            missing.append(name)
            print(f"[cpu] {name}: MISSING - {INSTALL_HINTS[name]}", flush=True)
    print(
        "[cpu] scope: this snapshot is CPU-only; Vulkan is never dispatched and backend completion is never claimed.",
        flush=True,
    )
    if missing:
        print(
            f"[cpu] FAILED: missing prerequisites: {', '.join(missing)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print("[cpu] SUCCESS: all required CPU prerequisites are available.", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bend_vulkan.py",
        description=(
            "Portable CPU-only checks for the bend-vulkan source snapshot. "
            "This CLI does not dispatch Vulkan and does not prove backend completion."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="run the portable CPU-only checks from the repository root")
    check.add_argument(
        "--f32",
        action="store_true",
        help="additionally run the CPU F32 parity end-to-end check with a fresh temporary output",
    )
    check.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=(
            "per-command timeout in seconds; must be finite and positive "
            f"(default: {DEFAULT_TIMEOUT:g})"
        ),
    )
    doctor = sub.add_parser(
        "doctor",
        help="diagnose whether the required CPU prerequisites are on PATH without running them",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="print a machine-readable JSON report on stdout instead of human text",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            if not math.isfinite(args.timeout) or args.timeout <= 0:
                raise CheckError(
                    f"--timeout must be a finite positive number of seconds (got {args.timeout!r})"
                )
            check_core(args.timeout)
            if args.f32:
                print("[cpu] optional F32 CPU parity end-to-end check", flush=True)
                check_f32(args.timeout)
            print(
                "[cpu] SUCCESS: portable CPU checks passed; no Vulkan dispatch was performed.",
                flush=True,
            )
            return 0
        if args.command == "doctor":
            return doctor_json() if args.json else doctor_human()
    except CheckError as exc:
        print(f"[cpu] FAILED: {exc}", file=sys.stderr, flush=True)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
