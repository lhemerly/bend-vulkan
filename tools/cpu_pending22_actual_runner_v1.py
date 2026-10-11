#!/usr/bin/env python3
"""Actual pending22 continuation runner.

Prepare mode performs source/evidence validation and creates one fresh bounded
delta. Execute mode additionally requires a newly reviewed grant and the
unchanged correctness-v2 host guard. Legacy runner code is loaded only from
pinned bytes with its real project path; the NEW integration-policy hash is
always the actual source hash of this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
E = ROOT / "evidence"
RUNNER = Path(__file__).resolve()

RUNNER_REL = "tools/cpu_pending22_actual_runner_v1.py"
OLD_RUNNER_REL = "tools/cpu_raw_baseline.py"
ADAPTER_REL = "tools/cpu_pending22_actual_adapter_v1.py"
VALIDATOR_REL = "tools/cpu_pending22_selection.py"
STORAGE_REL = "tools/cpu_delta_store.py"
OLD_SELECTION_REL = "evidence/cpu-v5-remaining87-preparation-v1/SELECTION.json"
OLD_MANIFEST_REL = "evidence/cpu-v5-remaining87-correctness-fresh-v2/DELTA.json"
OVERLAY_REL = "evidence/cpu-pending22-actual-preparation-v1/PENDING22-PROPOSAL.json"
RUN_SPEC_REL = "evidence/cpu-pending22-actual-preparation-v1/RUN-SPEC.json"
NEW_SELECTION_REL = "evidence/cpu-pending22-actual-preparation-v1/SELECTION.json"
OUTPUT_NAME = "cpu-pending22-correctness-fresh-v1"

OLD_RUNNER_SHA = "53ddaa2d2a427148c1d62e1d4c3a8a8693f892751a74ec079d74660eede3082f"
OLD_SELECTION_SHA = "58aece08b8be9da04b20433888383c8aa81d50bfdc31523960a0ab3a8ae50319"
OLD_MANIFEST_SHA = "7897aef53fcf48856a19f8d98835582e5f1160086d88aab94adbc18009b9085d"
STORAGE_SHA = "d0bc2f72e9028cc09b87999e19f8d499bed672cc60229893746d178bcfbbb1e5"
OVERLAY_SHA = "7dbb588abe5ecee0989d26cef92153733b12250d9e096b6c4745190eff8d38d4"
RUN_SPEC_SHA = "f6a68d4d3aa752d8c3bc1bcb257ccf0d36981ec5185509e82df6ca16623c90d2"
VALIDATOR_SHA = "adfa730bf25b8ff2c9e238f1788eb29604c196deb6aefa0a48a8e3d307586672"
V104_AUDIT_SHA = "9c912ab82492afa83c41b99a749f0234d559a9a0373ce012d63109c7c01babf4"
ACCEPTED_PROJECTION_SHA = "d8f4e408c4d24bbf08e79dfd8a03d5815f6e1837d8fb8748afcb81c010928197"

_HASH = re.compile(r"^[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_hash(value: str, label: str) -> str:
    require(
        isinstance(value, str) and _HASH.fullmatch(value) is not None,
        label + " must be a lowercase SHA256 digest",
    )
    return value


def identity(value: os.stat_result):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_pinned(path: Path, expected: str, limit: int, label: str) -> bytes:
    expected = require_hash(expected, label + " SHA256")
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, label + " realpath changed")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode) and before.st_size <= limit,
            label + " is not a bounded regular file",
        )
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        require(len(data) <= limit, label + " exceeds its bound")
        require(identity(before) == identity(after), label + " changed while read")
    finally:
        os.close(descriptor)
    require(sha(data) == expected, label + " file SHA256 changed")
    return data


def load_module(name: str, path: Path, expected: str, limit: int):
    path = Path(path).resolve()
    raw = read_pinned(path, expected, limit, name + " source")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


class ReviewedPending22Policy:
    """Proxy preserving the old Policy APIs while sealing the NEW source."""

    def __init__(self, legacy_module, legacy_policy, source_pins, selection_file_sha):
        self._legacy = legacy_policy
        self.module = legacy_module
        self.source = legacy_policy.source
        self.G = legacy_policy.G
        self.freeze = legacy_policy.freeze
        self.bundle = legacy_policy.bundle
        self._rows = legacy_policy._rows
        self._groups = legacy_policy._groups
        self.policy_source = RUNNER
        self.policy_sha = source_pins["new_runner"]
        self.selection_file_sha = selection_file_sha

        physical = {
            "pending22_runner": ROOT / RUNNER_REL,
            "pending22_adapter": ROOT / ADAPTER_REL,
            "pending22_validator": ROOT / VALIDATOR_REL,
            "historical_runner": ROOT / OLD_RUNNER_REL,
            "historical_old_selection": ROOT / OLD_SELECTION_REL,
            "historical_closed_manifest": ROOT / OLD_MANIFEST_REL,
            "pending22_overlay": ROOT / OVERLAY_REL,
            "pending22_run_spec": ROOT / RUN_SPEC_REL,
            "pending22_selection": ROOT / NEW_SELECTION_REL,
            "historical_v104_audit": ROOT / "evidence/cpu-pending22-actual-preparation-v1/V104-AUDIT.json",
        }
        pin_names = {
            "pending22_runner": "new_runner",
            "pending22_adapter": "new_adapter",
            "pending22_validator": "validator",
            "historical_runner": "old_runner",
            "historical_old_selection": "old_selection",
            "historical_closed_manifest": "old_manifest",
            "pending22_overlay": "overlay",
            "pending22_run_spec": "run_spec",
            "historical_v104_audit": "v104_audit",
        }
        require(set(pin_names) == set(physical) - {"pending22_selection"},
                "new policy physical pin map changed")
        for role, path in physical.items():
            legacy_policy.files[role] = path
            if role != "pending22_selection":
                legacy_policy.pins[role] = source_pins[pin_names[role]]
        legacy_policy.pins["pending22_selection"] = selection_file_sha
        legacy_policy.pins["accepted_pending22_projection"] = source_pins[
            "accepted_projection"
        ]
        self.files = legacy_policy.files
        self.pins = legacy_policy.pins
        self.buffers = legacy_policy.verify()

    def verify(self):
        require(
            sha(self.policy_source.read_bytes()) == self.policy_sha,
            "additive runner source changed",
        )
        self.buffers = self._legacy.verify()
        return self.buffers

    def row(self, path):
        return self._legacy.row(path)

    def eligible(self, path, purpose):
        return self._legacy.eligible(path, purpose)

    def pin_compiler_context(self, context):
        return self._legacy.pin_compiler_context(context)

    def compiler_context(self, strict):
        return self._legacy.compiler_context(strict)

    def binding(self, path, purpose):
        self.verify()
        require(
            sha(self.policy_source.read_bytes()) == self.policy_sha,
            "additive integration policy changed",
        )
        row, source, group = self.eligible(path, purpose)
        binding = {
            "approved_pins": dict(self.pins),
            "integration_policy_path": str(self.policy_source),
            "integration_policy_sha256": self.policy_sha,
            "path": path,
            "source_sha256": row["sha256"],
            "frozen_row_sha256": self.module.digest(row),
            "contract_group": group,
            "frozen_diagnostic": row["expected_output"],
            "purpose": purpose,
        }
        if group == "positive-runtime-contract-candidate":
            binding["raw_golden_binding"] = self.bundle.context(row, source)
        return binding

    def fresh_delta(self, selection, out):
        self.verify()
        require(selection["schema"] == "bend-pending22-actual-continuation-selection-v1",
                "new selection schema changed")
        paths = selection["selection"]
        require(
            len(paths) == len(set(paths)) == 22,
            "new runner requires exact unique22",
        )
        require(selection["purpose"] == "next-safe100", "selection purpose changed")
        require(selection["execution_authorized"] is False and
                selection["resume_authorized"] is False,
                "selection fabricated authorization")
        require(selection["source_sha256_by_path"] ==
                {path: selection["source_sha256_by_path"][path] for path in paths},
                "selection source scope changed")
        records = []
        for path in paths:
            row, _, group = self.eligible(path, selection["purpose"])
            require(row["sha256"] == selection["source_sha256_by_path"][path],
                    "selection source differs from frozen row: " + path)
            require(row["status"] == "pending" and row["risk"] == [],
                    "ineligible baseline row selected: " + path)
            require(group == selection["contract_groups_by_path"][path],
                    "selection contract group changed: " + path)
            require(self.module.digest(row) ==
                    selection["baseline_row_sha256_by_path"][path],
                    "selection baseline row changed: " + path)
            records.append(
                {
                    "path": path,
                    "source_sha256": row["sha256"],
                    "original_status": row["status"],
                    "original_risk": row["risk"],
                    "contract_group": group,
                    "status": "pending",
                    "stages": {},
                    "baseline_row_sha256": self.module.digest(row),
                }
            )

        binding = {
            "approved_pins": dict(self.pins),
            "integration_policy_path": str(self.policy_source),
            "integration_policy_sha256": self.policy_sha,
            "selection_sha256": self.module.digest(selection),
            "selection_file_sha256": self.selection_file_sha,
            "output_directory": str(out),
            "fresh_receipt_policy": "all22 fresh; no historical stage reattachment",
            "continuation_references": {
                "old_closed_manifest": {
                    "path": OLD_MANIFEST_REL,
                    "sha256": self.pins["historical_closed_manifest"],
                    "historical_reference_only": True,
                },
                "accepted_projection": {
                    "sha256": self.pins["accepted_pending22_projection"],
                    "recomputed_from_pinned_helper_inputs": True,
                },
                "old_selection": {
                    "path": OLD_SELECTION_REL,
                    "sha256": self.pins["historical_old_selection"],
                    "historical_reference_only": True,
                },
            },
        }
        return {
            "schema": "bend-strict-raw-golden-delta-v1",
            "binding": binding,
            "selection": selection,
            "baseline_ancestry": {
                "sha256": self.pins["baseline"],
                "rows_modified": 0,
                "receipts_reattached": 0,
            },
            "records": records,
            "GPU_dispatches": 0,
            "execution_started": False,
        }

    def dispatch(self, path, purpose, delta_row, callback, *args):
        binding = self.binding(path, purpose)
        require(
            delta_row["baseline_row_sha256"] == binding["frozen_row_sha256"],
            "mutable baseline row substituted",
        )
        result = callback(binding, *args)
        self.binding(path, purpose)
        return result


def require_fresh_pressure_review(selection, permit):
    require(selection["pressure_qualification_required"] is True,
            "fresh pressure qualification requirement changed")
    for key in (
        "resource_pressure_qualification_granted",
        "resource_admission_granted",
        "CPU_baseline_only",
        "fresh_resource_decision_review_passed",
        "parent_owned_reservation_review_passed",
    ):
        require(permit.get(key) is True, "missing fresh pressure/resource review: " + key)
    require(permit.get("supersedes_resource_hold_sha256") ==
            selection["resource_hold_anchor"]["sha256"],
            "fresh decision must identify the historical resource hold")
    require(permit.get("GPU_authorized") is False, "GPU authorization is forbidden")
    require(permit.get("project_only_free_route") is True,
            "project-only free route is required")
    require(permit.get("paid_fallback_authorized") is False,
            "paid fallback is forbidden")


def require_fresh_empty(delta):
    require(delta.get("execution_started") is False,
            "prepared execution_started must remain false")
    require(delta.get("GPU_dispatches") == 0, "fresh CPU-only delta required")
    require(delta.get("CPU_interval_released") is not True,
            "fresh delta is already released")
    records = delta["records"]
    require(len(records) == 22 and len({row["path"] for row in records}) == 22,
            "fresh exact22 records required")
    require(
        all(
            row.get("original_status") == "pending"
            and row.get("original_risk") == []
            and row.get("status") == "pending"
            and row.get("stages") == {}
            for row in records
        ),
        "every fresh record must be pending with an empty stage map",
    )
    require(
        delta["selection"]["fresh_execution_policy"][
            "historical_stage_objects_transferred"
        ]
        is False,
        "historical stage transfer is forbidden",
    )


def parser():
    result = argparse.ArgumentParser()
    result.add_argument("--selection", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--prepare-selection", action="store_true")
    result.add_argument("--selection-sha256")
    result.add_argument("--authorization")
    result.add_argument("--authorization-sha256")
    result.add_argument("--idle-host-guard-state")
    result.add_argument("--idle-host-policy-sha256")
    result.add_argument("--runner-sha256", required=True)
    result.add_argument("--adapter-sha256", required=True)
    result.add_argument("--validator-sha256", required=True)
    result.add_argument("--storage-sha256", required=True)
    result.add_argument("--old-selection-sha256", required=True)
    result.add_argument("--old-manifest-sha256", required=True)
    result.add_argument("--overlay-sha256", required=True)
    result.add_argument("--run-spec-sha256", required=True)
    result.add_argument("--accepted-projection-sha256", required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    require(args.selection == NEW_SELECTION_REL, "exact new selection path required")
    require(args.output == OUTPUT_NAME, "exact fresh output name required")

    source_pins = {
        "new_runner": require_hash(args.runner_sha256, "runner SHA256"),
        "new_adapter": require_hash(args.adapter_sha256, "adapter SHA256"),
        "validator": require_hash(args.validator_sha256, "validator SHA256"),
        "old_runner": OLD_RUNNER_SHA,
        "storage": require_hash(args.storage_sha256, "storage SHA256"),
        "old_selection": require_hash(
            args.old_selection_sha256, "old selection SHA256"
        ),
        "old_manifest": require_hash(
            args.old_manifest_sha256, "old manifest SHA256"
        ),
        "overlay": require_hash(args.overlay_sha256, "overlay SHA256"),
        "run_spec": require_hash(args.run_spec_sha256, "RUN-SPEC SHA256"),
        "v104_audit": V104_AUDIT_SHA,
        "accepted_projection": require_hash(
            args.accepted_projection_sha256, "accepted projection SHA256"
        ),
    }
    fixed_pins = {"old_runner": OLD_RUNNER_SHA, "old_selection": OLD_SELECTION_SHA,
                  "old_manifest": OLD_MANIFEST_SHA, "storage": STORAGE_SHA,
                  "overlay": OVERLAY_SHA, "run_spec": RUN_SPEC_SHA,
                  "validator": VALIDATOR_SHA, "accepted_projection": ACCEPTED_PROJECTION_SHA}
    require(all(source_pins[role] == expected for role, expected in fixed_pins.items()),
            "reviewed current evidence pin changed")
    require(not (args.execute and args.prepare_selection),
            "selection preparation cannot execute")
    if not args.prepare_selection:
        require_hash(args.selection_sha256, "new selection SHA256")

    require(RUNNER.resolve() == ROOT / RUNNER_REL,
            "runner no longer resides under the reviewed project tools directory")
    require(sha(RUNNER.read_bytes()) == source_pins["new_runner"],
            "additive runner source hash mismatch")

    adapter = load_module(
        "_reviewed_pending22_adapter",
        ROOT / ADAPTER_REL,
        source_pins["new_adapter"],
        262144,
    )
    require(adapter.ROOT == ROOT, "adapter ROOT differs from runner ROOT")

    legacy = load_module(
        "_historical_cpu_raw_baseline",
        ROOT / OLD_RUNNER_REL,
        OLD_RUNNER_SHA,
        65536,
    )
    require(legacy.ROOT == ROOT, "historical runner ROOT changed")
    require(
        legacy.SOURCE == ROOT.parent / "bend-vulkan-feasibility/source",
        "historical compiler/source context changed",
    )

    old_selection_raw = read_pinned(
        ROOT / OLD_SELECTION_REL,
        source_pins["old_selection"],
        65536,
        "old87 selection",
    )
    old_selection = json.loads(old_selection_raw)

    # This is deliberately the first old-evidence validation. The historical
    # Policy validates the complete old ancestry against exact old87 before the
    # accepted pending22 helper is invoked.
    legacy_policy = legacy.Policy()
    require(
        legacy_policy.policy_sha == OLD_RUNNER_SHA,
        "historical Policy did not bind its actual old runner source",
    )
    legacy_policy.bind_ancestry(old_selection)

    proof = adapter.validate_and_build(
        root=ROOT,
        old_policy=legacy_policy,
        source_pins=source_pins,
        selection_sha256=args.selection_sha256,
        prepare_selection=args.prepare_selection,
    )
    selection = proof["selection"]
    if args.prepare_selection:
        destination = ROOT / NEW_SELECTION_REL
        require(destination.parent.is_dir() and not destination.parent.is_symlink(),
                "preparation directory absent or changed")
        raw = adapter.encode(selection)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps({"selection_file_sha256": sha(raw), "prepared_selection_cases": 22,
                          "execution_authorized": False, "grant_created": False}))
        return

    policy = ReviewedPending22Policy(
        legacy,
        legacy_policy,
        source_pins,
        proof["selection_file_sha256"],
    )
    out = E / OUTPUT_NAME
    require(out.parent == E and not out.is_symlink(), "fresh output path changed")
    proposed = policy.fresh_delta(selection, out)

    # This retains the original strict/parser/resume APIs and compiler context.
    strict, _ = legacy.load_helpers(policy)
    delta_path = out / "DELTA.json"
    storage = legacy.verified_module(
        "_pending22_approved_delta_store",
        policy.files["persistence"],
        policy.buffers["persistence"],
    )
    if delta_path.exists():
        store = storage.Store(out)
        require(out.is_dir(), "prepared output directory is invalid")
        delta = store.load()
        legacy.validate_delta(delta, proposed)
        require_fresh_empty(delta)
    else:
        require(not args.execute, "execute requires an already prepared fresh delta")
        require(not out.exists(), "fresh output directory already exists")
        out.mkdir(mode=0o700)
        store = storage.Store(out)
        delta = proposed
        store.save(delta)
        require_fresh_empty(store.load())

    if not args.execute:
        print(
            json.dumps(
                {
                    "prepared_records": 22,
                    "old_historical_ancestry_validated": True,
                    "old_terminal_cases_classified": 65,
                    "old_pending_cases_selected": 22,
                    "historical_receipts_transferred": 0,
                    "baseline_rows_modified": 0,
                    "execution_started": False,
                    "CPU_PAUSE": (E / "CPU-PAUSE").exists(),
                    "integration_policy_sha256": policy.policy_sha,
                    "selection_file_sha256": proof["selection_file_sha256"],
                },
                indent=2,
            )
        )
        return

    require(args.authorization and args.authorization_sha256,
            "fresh reviewed authorization required")
    authorization = Path(args.authorization).resolve()
    require(
        authorization.is_relative_to(E.resolve()),
        "authorization outside project evidence",
    )
    authorization_raw = read_pinned(
        authorization,
        require_hash(args.authorization_sha256, "authorization SHA256"),
        65536,
        "fresh authorization",
    )
    permit = json.loads(authorization_raw)
    require(permit.get("schema") ==
            "bend-pending22-actual-continuation-grant-v1",
            "fresh pending22 grant schema required")
    require(permit.get("execution_authorized") is True and
            permit.get("new_trusted_grant") is True,
            "fresh trusted grant is absent")
    require(permit.get("historical_grant_reused") is False,
            "historical grant reuse is forbidden")
    require(permit.get("binding_review_passed") is True and
            permit.get("CPU_window_granted") is True,
            "fresh binding/CPU window approval absent")
    require(permit.get("integration_policy_sha256") == policy.policy_sha,
            "runtime receipt policy SHA differs from actual additive runner")
    require(permit.get("integration_policy_path") == str(RUNNER),
            "runtime receipt policy path differs from actual additive runner")
    require(permit.get("selection_file_sha256") ==
            proof["selection_file_sha256"],
            "grant selection file pin changed")
    require(permit.get("delta_binding") == delta["binding"],
            "fresh bounded delta binding mismatch")
    require(permit.get("source_pins", {}).get("runner") == policy.policy_sha and
            permit.get("source_pins", {}).get("adapter") == source_pins["new_adapter"],
            "grant runner/adapter pins changed")
    require(permit.get("idle_host_policy_review_passed") is True and
            permit.get("idle_host_policy_sha256") == args.idle_host_policy_sha256,
            "fresh exact idle-host policy review is absent")
    require_fresh_pressure_review(selection, permit)
    require_fresh_empty(delta)

    # configure_host_guard/run_step/execute_case are the pinned historical
    # implementations. Their __file__ context is the pinned historical source,
    # while every produced receipt basis uses this new policy/delta binding.
    require(args.idle_host_guard_state and args.idle_host_policy_sha256,
            "execution requires the existing supervisor-owned exact host guard")
    legacy.configure_host_guard(args)
    require(legacy.HOST_GUARD is not None, "required stage guard omitted")
    require(not (E / "CPU-PAUSE").exists(), "CPU scheduling pause present")
    try:
        delta["execution_started"] = True
        store.save(delta)
        for record in delta["records"]:
            record["status"] = legacy.execute_case(
                policy, strict, delta, record, out, lambda: store.save(delta)
            )
            if record["status"] == "pass-check-interpreter-printer-ineligible":
                record["C_JS_compiled_pass"] = False
            store.save(delta)
            print(record["path"], record["status"], flush=True)
    finally:
        (E / "CPU-PAUSE").touch()
        delta["CPU_interval_released"] = True
        store.save(delta)


if __name__ == "__main__":
    main()

