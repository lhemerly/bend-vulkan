#!/usr/bin/env python3
"""Reviewed-template supervisor for exact pending22.

The pressure, owned-process, signal, startup-pipe, wall, grace, cleanup,
subreaper, and host-guard mechanisms are reused byte-for-byte from the pinned
old supervisor module. Only fresh source/path pins and exact22 admission are
new. This file is not launchable until the source-only preparer replaces all
review placeholders and DELTA_SHA.
"""

import argparse
import ctypes
import datetime
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
E = ROOT / "evidence"
REVIEW = E / "cpu-pending22-actual-supervisor-v1"
OUTPUT_NAME = "cpu-pending22-correctness-fresh-v1"
SELECTION_REL = "evidence/cpu-pending22-actual-preparation-v1/SELECTION.json"
OLD_SELECTION_REL = "evidence/cpu-v5-remaining87-preparation-v1/SELECTION.json"
OLD_MANIFEST_REL = "evidence/cpu-v5-remaining87-correctness-fresh-v2/DELTA.json"
OVERLAY_REL = "evidence/cpu-pending22-actual-preparation-v1/PENDING22-PROPOSAL.json"
RUN_SPEC_REL = "evidence/cpu-pending22-actual-preparation-v1/RUN-SPEC.json"

RUNNER_REL = "tools/cpu_pending22_actual_runner_v1.py"
ADAPTER_REL = "tools/cpu_pending22_actual_adapter_v1.py"
VALIDATOR_REL = "tools/cpu_pending22_selection.py"
STORAGE_REL = "tools/cpu_delta_store.py"
OLD_RUNNER_REL = "tools/cpu_raw_baseline.py"
BASE_SUPERVISOR_REL = "tools/cpu_remaining87_supervisor_v2.py"
IDLE_GUARD_REL = "tools/cpu_correctness_host_guard_v2.py"

RUNNER_SHA = "__PENDING22_RUNNER_SHA256__"
ADAPTER_SHA = "__PENDING22_ADAPTER_SHA256__"
VALIDATOR_SHA = "__PENDING22_VALIDATOR_SHA256__"
STORAGE_SHA = "__PENDING22_STORAGE_SHA256__"
OLD_SELECTION_SHA = "__PENDING22_OLD_SELECTION_SHA256__"
OLD_MANIFEST_SHA = "__PENDING22_OLD_MANIFEST_SHA256__"
SELECTION_SHA = "__PENDING22_SELECTION_SHA256__"
OVERLAY_SHA = "__PENDING22_OVERLAY_SHA256__"
RUN_SPEC_SHA = "__PENDING22_RUN_SPEC_SHA256__"
ACCEPTED_PROJECTION_SHA = "__PENDING22_ACCEPTED_PROJECTION_SHA256__"
DELTA_SHA = "__PENDING22_DELTA_SHA256__"

BASE_SUPERVISOR_SHA = "eddaf5fcda2e24ec1168308514e67c487dc4dcbc5f38dd5d51336614fa1a2f2d"
V104_AUDIT_SHA = "9c912ab82492afa83c41b99a749f0234d559a9a0373ce012d63109c7c01babf4"
IDLE_GUARD_SHA = "d42c2ade497e19bfa95366be65a22b29acccdd8f58f732b143b359ac00658ac6"

PROTOCOL = dict(
    quiet_seconds=20,
    monitor_seconds=5,
    minimum_available_bytes=12 * 1024**3,
    maximum_PSI_some_full_avg10=0.10,
    allowed_new_swapout_pages=0,
    execution_wall_seconds=600,
    graceful_stop_seconds=35,
    forced_cleanup_seconds=5,
    startup_sampling_armed_before_Popen=True,
    blocking_Popen_hard_deadline_qualified=False,
    stage_limits_unchanged=True,
    sandbox_qualified=False,
    execution_authorized=False,
    cleanup_is_resource_admission=False,
    startup_gate="one-byte pipe, pause-clear before commit, cancellation latched",
    pause_write_failure="immediate owned cleanup, no grace",
    idle_host_policy=(
        "correctness-only v2: resident telemetry; exact reservation/identity/"
        "resource and overlap gates"
    ),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_base():
    path = ROOT / BASE_SUPERVISOR_REL
    raw = path.read_bytes()
    check(hashlib.sha256(raw).hexdigest() == BASE_SUPERVISOR_SHA,
          "pinned historical supervisor changed")
    module = types.ModuleType("_historical_remaining87_supervisor")
    module.__file__ = str(path.resolve())
    module.__package__ = ""
    module.__cached__ = None
    exec(compile(raw, str(path.resolve()), "exec"), module.__dict__)
    check(module.ROOT == ROOT, "historical supervisor ROOT changed")
    check((module.WALL, module.GRACE, module.KILL_WAIT, module.INTERVAL, module.QUIET)
          == (600, 35, 5, 5, 20),
          "historical startup/timeout mechanism changed")
    return module


def verify_inputs(pins):
    for path, expected in pins:
        check(sha(path) == expected, "reviewed input changed: " + str(path))


def expected_source_pins(supervisor_sha):
    return {
        "runner": RUNNER_SHA,
        "adapter": ADAPTER_SHA,
        "validator": VALIDATOR_SHA,
        "storage": STORAGE_SHA,
        "old_ancestry_selection": OLD_SELECTION_SHA,
        "pending22_selection": SELECTION_SHA,
        "old_manifest": OLD_MANIFEST_SHA,
        "overlay": OVERLAY_SHA,
        "run_spec": RUN_SPEC_SHA,
        "v104_audit": V104_AUDIT_SHA,
        "accepted_projection": ACCEPTED_PROJECTION_SHA,
        "old_runner": "53ddaa2d2a427148c1d62e1d4c3a8a8693f892751a74ec079d74660eede3082f",
        "base_supervisor": BASE_SUPERVISOR_SHA,
        "idle_guard": IDLE_GUARD_SHA,
        "delta": DELTA_SHA,
    }


def physical_pins(supervisor_sha):
    delta = E / OUTPUT_NAME / "DELTA.json"
    pins = [
        (ROOT / RUNNER_REL, RUNNER_SHA),
        (ROOT / ADAPTER_REL, ADAPTER_SHA),
        (ROOT / VALIDATOR_REL, VALIDATOR_SHA),
        (ROOT / STORAGE_REL, STORAGE_SHA),
        (ROOT / OLD_SELECTION_REL, OLD_SELECTION_SHA),
        (ROOT / SELECTION_REL, SELECTION_SHA),
        (ROOT / OLD_MANIFEST_REL, OLD_MANIFEST_SHA),
        (ROOT / OVERLAY_REL, OVERLAY_SHA),
        (ROOT / RUN_SPEC_REL, RUN_SPEC_SHA),
        (ROOT / "evidence/cpu-pending22-actual-preparation-v1/V104-AUDIT.json", V104_AUDIT_SHA),
        (ROOT / OLD_RUNNER_REL,
         "53ddaa2d2a427148c1d62e1d4c3a8a8693f892751a74ec079d74660eede3082f"),
        (ROOT / BASE_SUPERVISOR_REL, BASE_SUPERVISOR_SHA),
        (ROOT / IDLE_GUARD_REL, IDLE_GUARD_SHA),
        (delta, DELTA_SHA),
    ]
    return pins


def read_prepared_delta(path, runner):
    check(path == E / OUTPUT_NAME / "DELTA.json", "wrong exact pending22 delta path")
    selection_path = ROOT / SELECTION_REL
    selection_raw = selection_path.read_bytes()
    check(hashlib.sha256(selection_raw).hexdigest() == SELECTION_SHA,
          "new selection bytes changed")
    selection = json.loads(selection_raw)

    source = ROOT / STORAGE_REL
    before_manifest = path.read_bytes()
    check(hashlib.sha256(before_manifest).hexdigest() == DELTA_SHA, "fresh delta pin changed")
    raw = source.read_bytes()
    check(hashlib.sha256(raw).hexdigest() == STORAGE_SHA,
          "bounded storage source changed")
    module = types.ModuleType("_pending22_supervisor_bounded_reader")
    module.__file__ = str(source.resolve())
    module.__package__ = ""
    module.__cached__ = None
    exec(compile(raw, str(source.resolve()), "exec"), module.__dict__)
    delta = module.Store(path.parent).load()
    check(path.read_bytes() == before_manifest, "fresh delta changed during load")

    check(delta.get("schema") == "bend-strict-raw-golden-delta-v1",
          "unexpected pending22 delta schema")
    check(delta.get("selection") == selection,
          "fresh delta selection differs from reviewed selection file")
    check(len(delta["records"]) == 22 and len({row["path"] for row in delta["records"]}) == 22,
          "exact pending22 required")
    check([row["path"] for row in delta["records"]] == selection["selection"],
          "fresh record order differs from exact selection")
    check(all(row["source_sha256"] == selection["source_sha256_by_path"][row["path"]]
              and row["baseline_row_sha256"] == selection["baseline_row_sha256_by_path"][row["path"]]
              and row["contract_group"] == selection["contract_groups_by_path"][row["path"]]
              for row in delta["records"]), "fresh frozen row/source/group binding changed")
    check(all(row["status"] == "pending" and row["stages"] == {} for row in delta["records"]),
          "all22 records must be pending with empty receipts")
    check(all(row.get("original_status") == "pending" and row.get("original_risk") == []
              for row in delta["records"]),
          "fresh records do not retain original frozen eligibility")
    check(delta.get("execution_started") is False and delta.get("GPU_dispatches") == 0,
          "fresh unstarted CPU-only delta required")
    check(delta.get("CPU_interval_released") is not True,
          "prepared interval is already released")
    check(delta["baseline_ancestry"] == {
        "sha256": "a1a500c6c1c4aad7c79f9086e3381420b13dbd179c5558dc6b97659923dcaa1d",
        "rows_modified": 0,
        "receipts_reattached": 0,
    }, "fresh baseline ancestry changed")

    binding = delta["binding"]
    check(binding["integration_policy_path"] == str((ROOT / RUNNER_REL).resolve()),
          "runtime receipt integration path is not the additive runner")
    check(binding["integration_policy_sha256"] == sha(runner) == RUNNER_SHA,
          "runtime receipt integration SHA is not the actual additive runner")
    check(binding["selection_file_sha256"] == SELECTION_SHA,
          "binding selection file SHA changed")
    logical_selection_sha = hashlib.sha256(
        json.dumps(selection, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    check(binding["selection_sha256"] == logical_selection_sha,
          "logical selection digest changed")
    check(binding["output_directory"] == str(path.parent),
          "fresh output binding changed")
    check(binding["fresh_receipt_policy"] ==
          "all22 fresh; no historical stage reattachment",
          "fresh receipt policy changed")

    approved = binding.get("approved_pins", {})
    expected_approved = {
        "pending22_runner": RUNNER_SHA,
        "pending22_adapter": ADAPTER_SHA,
        "pending22_validator": VALIDATOR_SHA,
        "persistence": STORAGE_SHA,
        "historical_old_selection": OLD_SELECTION_SHA,
        "pending22_selection": SELECTION_SHA,
        "historical_closed_manifest": OLD_MANIFEST_SHA,
        "pending22_overlay": OVERLAY_SHA,
        "pending22_run_spec": RUN_SPEC_SHA,
        "historical_v104_audit": V104_AUDIT_SHA,
        "accepted_pending22_projection": ACCEPTED_PROJECTION_SHA,
    }
    for role, expected in expected_approved.items():
        check(approved.get(role) == expected, "fresh binding pin changed: " + role)

    references = binding.get("continuation_references", {})
    check(references.get("old_closed_manifest") == {
        "path": OLD_MANIFEST_REL,
        "sha256": OLD_MANIFEST_SHA,
        "historical_reference_only": True,
    }, "closed old manifest reference changed")
    check(references.get("accepted_projection") == {
        "sha256": ACCEPTED_PROJECTION_SHA,
        "recomputed_from_pinned_helper_inputs": True,
    }, "accepted projection reference changed")
    check(references.get("old_selection") == {
        "path": OLD_SELECTION_REL, "sha256": OLD_SELECTION_SHA,
        "historical_reference_only": True,
    }, "old selection reference changed")
    return delta


def utc(value):
    check(isinstance(value, str), "UTC timestamp must be a string")
    try:
        result = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("invalid UTC timestamp: " + str(error))
    check(result.tzinfo is not None, "UTC timestamp lacks timezone")
    return result.astimezone(datetime.timezone.utc)


def check_fresh_grant_window(grant, now=None, monotonic_now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
    interval = grant.get("parent_interval")
    check(isinstance(interval, dict), "fresh parent interval required")
    check(interval.get("owner") == "parent" and interval.get("exclusive") is True,
          "parent-owned exclusive interval required")
    check(interval.get("state") == "active", "parent interval is not active")
    check(isinstance(interval.get("id"), str) and interval["id"],
          "parent interval ID required")
    start = utc(interval.get("starts_utc"))
    end = utc(interval.get("ends_utc"))
    check(start <= now < end, "current time is outside fresh parent interval")
    check(0 < (end - start).total_seconds() <= 660, "parent interval exceeds 660 seconds")
    check((end - now).total_seconds() > 20 + 35 + 5,
          "exclusive interval lacks qualification and cleanup reserve")

    activity = grant.get("user_activity_admission")
    check(isinstance(activity, dict), "fresh user-activity admission required")
    check(activity.get("full_admission_checked") is True and
          activity.get("qualifying_activity_resolved") is True,
          "Steam/Godot activity was not resolved")
    check(activity.get("steam_and_godot_resolution") ==
          "cleared-by-parent-before-admission",
          "Steam/Godot resolution is absent")
    checked = utc(activity.get("admission_checked_utc"))
    age = (now - checked).total_seconds()
    check(0 <= age <= 120, "user-activity admission evidence is not fresh")
    return monotonic_now + (end - now).total_seconds()


def write_fresh(path, data):
    path = Path(path)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "w") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--execute", action="store_true")
    args.add_argument("--authorization")
    args.add_argument("--authorization-sha256")
    args.add_argument("--idle-host-policy")
    args.add_argument("--idle-host-policy-sha256")
    args = args.parse_args()
    if not args.execute:
        print(json.dumps(PROTOCOL, indent=2))
        return

    base = load_base()
    check(args.authorization and args.authorization_sha256,
          "fresh trusted grant required")
    authorization = Path(args.authorization).resolve()
    check(authorization.is_relative_to(E.resolve()),
          "grant outside project evidence")
    authorization_raw = authorization.read_bytes()
    check(hashlib.sha256(authorization_raw).hexdigest() == args.authorization_sha256,
          "fresh grant hash changed")
    grant = json.loads(authorization_raw)
    supervisor_path = Path(__file__).resolve()
    supervisor_sha = sha(supervisor_path)
    expected_pins = expected_source_pins(supervisor_sha)

    check(grant.get("schema") == "bend-pending22-actual-continuation-grant-v1",
          "fresh pending22 grant schema required")
    check(grant.get("execution_authorized") is True and
          grant.get("new_trusted_grant") is True,
          "fresh trusted execution grant absent")
    check(grant.get("supervisor_review_passed") is True and
          grant.get("supervisor_sha256") == supervisor_sha,
          "bound pending22 supervisor review absent")
    check(grant.get("source_pins") == expected_pins,
          "fresh grant source-pin map changed")
    check(grant.get("integration_policy_sha256") == RUNNER_SHA and
          grant.get("integration_policy_path") == str((ROOT / RUNNER_REL).resolve()),
          "grant integration source differs from additive runner")
    check(grant.get("selection_file_sha256") == SELECTION_SHA,
          "grant selection pin changed")
    check(grant.get("historical_grant_reused") is False and
          grant.get("historical_approval_denials_bypassed") is False,
          "historical grant/denial bypass is forbidden")
    check(grant.get("current_workload_launch_status") in
          ("not-attempted", "not-attempted-or-denied"),
          "current workload has already been attempted or denied")
    check(grant.get("project_only_free_route") is True and
          grant.get("paid_fallback_authorized") is False and
          grant.get("GPU_authorized") is False,
          "project-only CPU/free/no-GPU route changed")
    check(grant.get("execution_wall_seconds") == 600,
          "fresh execution ceiling changed")
    for key in (
        "binding_review_passed",
        "CPU_window_granted",
        "resource_pressure_qualification_granted",
        "resource_admission_granted",
        "CPU_baseline_only",
        "fresh_policy_review_passed",
        "fresh_reservation_review_passed",
        "fresh_resource_decision_review_passed",
        "parent_owned_reservation_review_passed",
        "idle_host_policy_review_passed",
    ):
        check(grant.get(key) is True, "missing fresh grant review: " + key)
    check(grant.get("supervisor_protocol") == PROTOCOL, "supervisor protocol changed")
    absolute_deadline = check_fresh_grant_window(grant)

    runner = ROOT / RUNNER_REL
    delta = E / OUTPUT_NAME / "DELTA.json"
    pins = physical_pins(supervisor_sha)
    pins.append((authorization, args.authorization_sha256))
    verify_inputs(pins)
    prepared = read_prepared_delta(delta, runner)
    check(grant.get("delta_binding") == prepared["binding"],
          "fresh exact22 delta binding mismatch")
    check(grant.get("idle_host_policy_sha256") == args.idle_host_policy_sha256,
          "grant idle-policy pin changed")
    check(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0,
          "subreaper unavailable")

    check(REVIEW.resolve().is_relative_to(E.resolve()),
          "pending22 review directory is outside evidence")
    check(REVIEW.is_dir() and not REVIEW.is_symlink(),
          "fresh pending22 review directory is absent")
    pause_path = E / "CPU-PAUSE"
    pause = pause_path.touch
    child = None
    owned = {}
    state = base.new_state()
    # Bias the unchanged base wall/grace/cleanup ceilings to the absolute grant end.
    state["begin"] = min(state["begin"], absolute_deadline - base.WALL - base.GRACE - base.KILL_WAIT)
    preflight = None
    gate_read = None
    gate_write = None
    result = dict(process_cleanup_complete=False, errors=[])

    def cancelled(signum, frame):
        if state is not None:
            base.stop(state, "supervisor signal " + str(signum))
            base.safe_pause(state, pause)

    def alarm(signum, frame):
        if time.monotonic() >= absolute_deadline - base.GRACE - base.KILL_WAIT:
            base.stop(state, "absolute parent execution deadline")
            base.safe_pause(state, pause)
            if preflight is None:
                raise RuntimeError("absolute deadline during admission")
        elif preflight is not None:
            base.tick(state, preflight[0]["pswpout"], pause)
        remaining = absolute_deadline - base.GRACE - base.KILL_WAIT - time.monotonic()
        if remaining > 0:
            signal.setitimer(signal.ITIMER_REAL, min(base.INTERVAL, remaining))

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, cancelled)
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, max(0.000001, min(base.INTERVAL, absolute_deadline - base.GRACE - base.KILL_WAIT - time.monotonic())))
    try:
        check(args.idle_host_policy and args.idle_host_policy_sha256,
              "fresh correctness-v2 policy required")
        check(grant.get("idle_host_policy_review_passed") is True and
              grant.get("idle_host_policy_sha256") == args.idle_host_policy_sha256,
              "exact idle-host review absent")
        policy_path = Path(args.idle_host_policy).resolve()
        check(policy_path.is_relative_to(E.resolve()),
              "idle-host policy outside evidence")
        guard_path = ROOT / IDLE_GUARD_REL
        guard_raw = guard_path.read_bytes()
        check(hashlib.sha256(guard_raw).hexdigest() == IDLE_GUARD_SHA ==
              grant.get("idle_guard_source_sha256"),
              "idle-host guard source changed")
        module = types.ModuleType("cpu_idle_host_guard_pending22")
        module.__file__ = str(guard_path)
        module.__package__ = ""
        module.__cached__ = None
        exec(compile(guard_raw, str(guard_path), "exec"), module.__dict__)
        policy_raw = policy_path.read_bytes()
        check(hashlib.sha256(policy_raw).hexdigest() == args.idle_host_policy_sha256,
              "fresh correctness policy changed")
        correctness_policy = json.loads(policy_raw)
        module.validate_policy(correctness_policy)
        check(grant.get("parent_owned_reservation") ==
              correctness_policy["reservation"],
              "fresh parent reservation is not bound to policy/grant")
        guard_directory = E / (
            "cpu-correctness-host-window-" + args.authorization_sha256
        )
        guard = module.IdleGuard.create(
            policy_path,
            args.idle_host_policy_sha256,
            args.authorization_sha256,
            guard_directory,
        )
        state["idle_guard"] = guard
        qualification = guard.qualify()
        preflight = [record["pressure"] for record in qualification]
        pins = pins + [
            (policy_path, args.idle_host_policy_sha256),
            (guard_path, IDLE_GUARD_SHA),
        ]
        verify_inputs(pins)
        check(state["stopped"] is None, "cancelled during fresh admission")

        # Do not reset the absolute grant budget after qualification.
        alarm(None, None)
        base.tick(state, preflight[0]["pswpout"], pause)
        check(state["stopped"] is None, "startup admission stopped")
        guard.check()
        gate_read, gate_write = os.pipe()
        command = [
            sys.executable,
            "-I",
            "-c",
            base.LIMIT_SHIM,
            str(gate_read),
            sys.executable,
            "-I",
            str(runner),
            "--selection",
            SELECTION_REL,
            "--output",
            OUTPUT_NAME,
            "--execute",
            "--authorization",
            str(authorization),
            "--authorization-sha256",
            args.authorization_sha256,
            "--idle-host-guard-state",
            str(guard_directory),
            "--idle-host-policy-sha256",
            args.idle_host_policy_sha256,
            "--selection-sha256",
            SELECTION_SHA,
            "--runner-sha256",
            RUNNER_SHA,
            "--adapter-sha256",
            ADAPTER_SHA,
            "--validator-sha256",
            VALIDATOR_SHA,
            "--storage-sha256",
            STORAGE_SHA,
            "--old-selection-sha256",
            OLD_SELECTION_SHA,
            "--old-manifest-sha256",
            OLD_MANIFEST_SHA,
            "--overlay-sha256",
            OVERLAY_SHA,
            "--run-spec-sha256",
            RUN_SPEC_SHA,
            "--accepted-projection-sha256",
            ACCEPTED_PROJECTION_SHA,
        ]
        with (REVIEW / "runner.stdout").open("xb") as stdout, (
            REVIEW / "runner.stderr"
        ).open("xb") as stderr:
            child = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
                pass_fds=(gate_read,),
                env={"PATH": os.environ["PATH"], "LANG": "C"},
            )
            os.close(gate_read)
            gate_read = None
            base.discover_owned(owned, base.processes(), os.getpid())
            base.tick(state, preflight[0]["pswpout"], pause)

            def clear_ready_pause():
                guard.check()
                pause_path.unlink(missing_ok=True)

            base.release_startup(
                state,
                pause,
                clear_ready_pause,
                lambda: os.write(gate_write, b"G"),
            )
            os.close(gate_write)
            gate_write = None
            signal.setitimer(signal.ITIMER_REAL, 0)
            result = base.supervise(
                child,
                preflight[0]["pswpout"],
                owned,
                pause,
                state,
            )
            result["preflight_samples"] = preflight
    except Exception as error:
        result["errors"].append("lifecycle: " + repr(error))
        if state is not None:
            base.stop(state, "lifecycle failure")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for descriptor in (gate_read, gate_write):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except Exception as error:
                    result["errors"].append("gate close: " + repr(error))
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            signal.signal(sig, signal.SIG_IGN)
        if state is not None and "cleanup_finished_monotonic" not in result:
            original_errors = result["errors"]
            result = base.cleanup(child, owned, state, pause)
            result["errors"].extend(original_errors)
        else:
            try:
                pause()
                result["pause_write_succeeded"] = True
            except Exception as error:
                result["pause_write_succeeded"] = False
                result["errors"].append("final pause: " + repr(error))
        if state.get("idle_guard") is not None:
            try:
                state["idle_guard"].finish()
                result["idle_host_window_closed"] = True
            except Exception as error:
                result["errors"].append("idle-host close: " + repr(error))

        held = base.held_coordination(result)
        try:
            write_fresh(
                REVIEW / "SUPERVISOR-RESULT.json",
                json.dumps(held, indent=2) + "\n",
            )
        except Exception as error:
            print("held pending22 result write failed: " + repr(error), file=sys.stderr)
        try:
            write_fresh(
                E / "BASELINE-PENDING22-CPU-RELEASE.json",
                json.dumps(held, indent=2) + "\n",
            )
        except Exception as error:
            print(
                "held pending22 coordination write failed: " + repr(error),
                file=sys.stderr,
            )

    check(
        result.get("process_cleanup_complete")
        and not result["errors"]
        and result.get("runner_exit") == 0,
        "pending22 supervisor failed; resource hold retained",
    )


if __name__ == "__main__":
    main()

