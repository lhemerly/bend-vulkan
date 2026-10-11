"""Read-only exact-old-pending22 reconciliation for the actual continuation.

This adapter never writes files, grants, policies, reservations, pauses,
receipts, manifests, or processes. It recomputes the accepted projection from
the pinned validator, closed old manifest, storage reader, and immutable
overlay, then proves that the continuation selection is exactly the old
pending22 and excludes all 65 historical terminal records.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
import types
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
E = ROOT / "evidence"

OLD_RESULT_REL = "evidence/cpu-v5-remaining87-correctness-fresh-v2"
OLD_SELECTION_REL = "evidence/cpu-v5-remaining87-preparation-v1/SELECTION.json"
NEW_SELECTION_REL = "evidence/cpu-pending22-actual-preparation-v1/SELECTION.json"
OVERLAY_REL = "evidence/cpu-pending22-actual-preparation-v1/PENDING22-PROPOSAL.json"
RUN_SPEC_REL = "evidence/cpu-pending22-actual-preparation-v1/RUN-SPEC.json"

PHYSICAL_SOURCE_PINS = {
    "new_runner": "tools/cpu_pending22_actual_runner_v1.py",
    "new_adapter": "tools/cpu_pending22_actual_adapter_v1.py",
    "validator": "tools/cpu_pending22_selection.py",
    "old_runner": "tools/cpu_raw_baseline.py",
    "storage": "tools/cpu_delta_store.py",
    "old_selection": OLD_SELECTION_REL,
    "old_manifest": OLD_RESULT_REL + "/DELTA.json",
    "overlay": OVERLAY_REL,
    "run_spec": RUN_SPEC_REL,
    "v104_audit": "evidence/cpu-pending22-actual-preparation-v1/V104-AUDIT.json",
}

SOURCE_LIMITS = {
    "new_runner": 262144,
    "new_adapter": 262144,
    "validator": 65536,
    "old_runner": 65536,
    "storage": 65536,
    "old_selection": 65536,
    "old_manifest": 262144,
    "overlay": 65536,
    "run_spec": 65536,
    "v104_audit": 65536,
}

SELECTION_SCHEMA = "bend-pending22-actual-continuation-selection-v1"
HISTORICAL_STATUS_COUNTS = {
    "pass-check-interpreter-printer-ineligible": 6,
    "pass-CPU-lanes-default-C-parity": 15,
    "pass-expected-negative": 35,
    "pass-check-interpreter": 9,
}
PENDING_CONTRACT_COUNTS = {
    "checker-negative-contract": 9,
    "positive-runtime-contract-candidate": 13,
}
OP_LET_STAGES = [
    "build-c",
    "check",
    "emit-fork-c",
    "emit-js",
    "emit-upstream-c",
    "interp",
    "native-t1",
    "native-t2",
]

_HASH = re.compile(r"^[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_hash(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and _HASH.fullmatch(value) is not None,
        label + " must be a lowercase SHA256 digest",
    )
    return value


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8") + b"\n"


def row_digest(value: Any) -> str:
    # Match cpu_raw_baseline.digest, including its deliberate omission of
    # the trailing newline.
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _identity(value: os.stat_result):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_pinned(path: Path, expected: str, limit: int, label: str):
    expected = require_hash(expected, label + " SHA256")
    path = Path(path)
    require(path.is_absolute(), label + " path must be absolute")
    require(path.resolve() == path, label + " realpath changed")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
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
        require(len(data) <= limit, label + " exceeds its byte bound")
        require(_identity(before) == _identity(after), label + " changed while read")
    finally:
        os.close(descriptor)
    require(digest(data) == expected, label + " file SHA256 changed")
    return data, _identity(after)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + repr(key))
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise RuntimeError("non-finite JSON number: " + value)


def parse_json(data: bytes, label: str) -> Dict[str, Any]:
    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )
    require(isinstance(value, dict), label + " must be an object")
    return value


def execute_pinned(name: str, path: Path, data: bytes, expected: str):
    require(digest(data) == expected, name + " source changed before execution")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    # Dataclasses with postponed annotations resolve the defining module via
    # sys.modules, just as they do during a normal Python import.
    missing = object()
    previous = sys.modules.get(name, missing)
    sys.modules[name] = module
    try:
        exec(compile(data, str(path), "exec"), module.__dict__)
    except BaseException:
        if previous is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


def validate_and_build(*, root: Path, old_policy, source_pins: Dict[str, str],
                       selection_sha256=None, prepare_selection=False):
    root = Path(root).resolve()
    require(root == ROOT, "adapter must retain the original project ROOT")
    expected_roles = set(PHYSICAL_SOURCE_PINS) | {"accepted_projection"}
    require(set(source_pins) == expected_roles, "continuation source-pin scope changed")
    for role in expected_roles:
        require_hash(source_pins[role], "source pin " + role)

    captured = {}
    paths = {}
    identities = {}
    for role, relative in PHYSICAL_SOURCE_PINS.items():
        path = root / relative
        require(path.resolve() == path, "source realpath changed: " + role)
        captured[role], identities[role] = read_pinned(
            path, source_pins[role], SOURCE_LIMITS[role], "source " + role
        )
        paths[role] = path

    old_selection = parse_json(captured["old_selection"], "old87 selection")
    run_spec = parse_json(captured["run_spec"], "pending22 RUN-SPEC")
    old_result_dir = root / OLD_RESULT_REL
    manifest_path = paths["old_manifest"]

    # The accepted helper remains the authority for the closed old manifest,
    # its 87 records, the immutable overlay, and the canonical accepted output.
    validator = execute_pinned(
        "_pending22_accepted_validator",
        paths["validator"],
        captured["validator"],
        source_pins["validator"],
    )
    projection = validator.load_current_evidence(
        original_result_dir=old_result_dir,
        expected_manifest_sha256=source_pins["old_manifest"],
        reader_path=paths["storage"],
        expected_reader_sha256=source_pins["storage"],
        overlay_path=paths["overlay"],
        expected_overlay_sha256=source_pins["overlay"],
    )
    require(
        digest(encode(projection)) == source_pins["accepted_projection"],
        "recomputed accepted projection differs from its reviewed SHA256",
    )

    # Independently load the same bounded storage API and prove the exact
    # pending/terminal partition rather than trusting only the projection list.
    storage = execute_pinned(
        "_pending22_closed_old_store",
        paths["storage"],
        captured["storage"],
        source_pins["storage"],
    )
    before = parse_json(captured["old_manifest"], "old manifest before load")
    store = storage.Store(old_result_dir)
    old_delta = store.load()
    after_bytes, after_identity = read_pinned(
        manifest_path,
        source_pins["old_manifest"],
        SOURCE_LIMITS["old_manifest"],
        "old manifest after load",
    )
    require(captured["old_manifest"] == after_bytes and
            identities["old_manifest"] == after_identity,
            "old manifest changed during load")
    after = parse_json(after_bytes, "old manifest after load")
    require(before == after, "old manifest semantic bytes changed during load")

    require(old_delta.get("schema") == "bend-strict-raw-golden-delta-v1", "old delta schema changed")
    require(old_delta.get("selection") == old_selection, "old logical selection was rebound")
    require(
        old_delta["binding"]["integration_policy_sha256"] == source_pins["old_runner"],
        "closed old manifest no longer identifies the historical runner source",
    )
    require(
        projection["old_manifest_ancestry"]["logical_binding"][
            "integration_policy_sha256"
        ]
        == source_pins["old_runner"],
        "accepted projection replaced the historical integration pin",
    )
    require(
        projection["old_manifest_ancestry"]["logical_binding_reference_only"] is True,
        "historical old logical binding is not reference-only",
    )

    old_paths = old_selection.get("selection")
    old_sources = old_selection.get("source_sha256_by_path")
    require(isinstance(old_paths, list) and len(old_paths) == len(set(old_paths)) == 87,
            "old selection is not exact unique87")
    require(isinstance(old_sources, dict) and set(old_sources) == set(old_paths),
            "old selection source scope changed")
    records = old_delta.get("records")
    require(isinstance(records, list) and len(records) == 87, "old record count changed")
    require([record.get("path") for record in records] == old_paths,
            "old records no longer preserve the old87 order")

    status_counts = {
        status: 0 for status in HISTORICAL_STATUS_COUNTS
    }
    pending_records = []
    terminal_records = []
    for record in records:
        path = record.get("path")
        require(path in old_sources, "old record path is outside old selection: " + str(path))
        require(record.get("original_status") == "pending", "historical original status changed")
        require(record.get("original_risk") == [], "historical risk list changed")
        require(record.get("source_sha256") == old_sources[path], "historical source pin changed")
        require(isinstance(record.get("stages"), dict), "historical stages are not an object")
        status = record.get("status")
        if status == "pending":
            pending_records.append(record)
        else:
            require(status in HISTORICAL_STATUS_COUNTS, "unknown historical status: " + str(status))
            require(record.get("stages"), "historical terminal record has no receipts")
            if status == "pass-check-interpreter-printer-ineligible":
                require(record.get("C_JS_compiled_pass") is False,
                        "printer-ineligible compiled-pass flag changed")
            status_counts[status] += 1
            terminal_records.append(record)

    require(status_counts == HISTORICAL_STATUS_COUNTS,
            "exact old65 terminal classification changed: " + repr(status_counts))
    require(len(pending_records) == 22 and len(terminal_records) == 65,
            "old pending22/terminal65 partition changed")
    pending_paths = [record["path"] for record in pending_records]
    terminal_paths = [record["path"] for record in terminal_records]
    require(set(pending_paths).isdisjoint(terminal_paths), "pending22 intersects old65 terminal set")
    require(set(pending_paths).issubset(old_paths), "pending22 is not a subset of old87")
    require(all(not record["stages"] for record in pending_records if record["path"] != "tests/parse/op_let.bend"),
            "an old pending case unexpectedly has historical stage receipts")
    op_let = next(record for record in pending_records if record["path"] == "tests/parse/op_let.bend")
    require(list(op_let["stages"]) == OP_LET_STAGES, "historical op_let stage list changed")

    require(projection.get("selected_paths") == pending_paths,
            "accepted projection is not exact old pending22 order")
    require(projection.get("source_sha256_by_path") ==
            {record["path"]: record["source_sha256"] for record in pending_records},
            "accepted projection source map differs from old pending records")
    require(projection.get("admission_claimed") is False and
            projection.get("execution_authorized") is False and
            projection.get("resume_authorized") is False,
            "accepted projection fabricated admission")
    require(projection["fresh_empty_receipts_policy"][
        "historical_stage_objects_transferred"
    ] is False, "historical stage objects were transferred")
    require(projection["fresh_empty_receipts_policy"][
        "op_let_requires_complete_fresh_run"
    ] is True, "op_let no longer requires a complete fresh run")

    # Validate the exact reviewed contracts against the original frozen rows.
    require(run_spec.get("schema") == "bend-pending22-actual-continuation-spec-v1",
            "unexpected RUN-SPEC schema")
    require(run_spec.get("execution_authorized") is False and run_spec.get("new_grant") is None,
            "RUN-SPEC fabricated authorization")
    require(run_spec.get("old_manifest_sha256") == source_pins["old_manifest"],
            "RUN-SPEC old manifest pin changed")
    require(run_spec.get("accepted_projection_sha256") == source_pins["accepted_projection"],
            "RUN-SPEC accepted projection pin changed")
    require(run_spec.get("fresh_output_name") == "cpu-pending22-correctness-fresh-v1",
            "RUN-SPEC output name changed")
    require(run_spec.get("receipt_policy") ==
            "all22 fresh; preserve old65 terminal cases and op_let8 historical stages without reattachment",
            "RUN-SPEC fresh receipt policy changed")
    require(run_spec.get("counts") == {
        "total22": 22,
        "expected_negative9": 9,
        "positive13": 13,
        "positive_compiled_candidates11": 11,
        "positive_interpreter_only2": 2,
        "non_main_module_cases4": 4,
    }, "RUN-SPEC contract counts changed")
    require(run_spec["limits"]["execution_wall_seconds"] == 600,
            "RUN-SPEC execution ceiling is not 600 seconds")
    for key, value in {
        "qualification_seconds": 20,
        "grace_seconds": 35,
        "cleanup_seconds": 5,
        "minimum_available_bytes": 12884901888,
        "maximum_PSI_some_full_avg10": 0.1,
        "new_swapout_pages": 0,
        "stage_timeout_seconds": 15,
        "C_build_timeout_seconds": 30,
        "native_or_JS_timeout_seconds": 5,
        "native_threads": [1, 2],
        "CPU_temperature_monitor": False,
    }.items():
        require(run_spec["limits"].get(key) == value, "RUN-SPEC limit changed: " + key)

    spec_cases = run_spec.get("cases")
    require(isinstance(spec_cases, list) and len(spec_cases) == 22,
            "RUN-SPEC does not contain exact22")
    require([case.get("path") for case in spec_cases] == pending_paths,
            "RUN-SPEC order differs from old pending22")
    pending_by_path = {record["path"]: record for record in pending_records}
    positive_compiled = 0
    positive_interpreter_only = 0
    non_main = 0
    negative_count = 0
    positive_count = 0
    for case in spec_cases:
        path = case["path"]
        record = pending_by_path[path]
        row = old_policy.row(path)
        require(row.get("sha256") == case.get("source_sha256") == record["source_sha256"],
                "frozen source hash changed: " + path)
        require(row.get("status") == "pending" and row.get("risk") == [],
                "frozen baseline eligibility changed: " + path)
        require(row.get("expected_output") == case.get("expected_output"),
                "exact frozen stdout contract changed: " + path)
        require(row.get("main_marker_per_upstream_gate") == case.get("main_marker"),
                "main/non-main gate changed: " + path)
        require(row_digest(row) == record["baseline_row_sha256"] == case["baseline_row_sha256"],
                "frozen baseline row changed: " + path)
        _, _, group = old_policy.eligible(path, "next-safe100")
        require(group == record["contract_group"] == case["contract_group"],
                "frozen contract group changed: " + path)
        candidates = case.get("compiled_candidates")
        require(isinstance(candidates, list), "compiled candidate list is invalid: " + path)
        require(row.get("candidate_compiled_lanes_per_upstream_gate") == candidates,
                "compiled eligibility changed: " + path)
        expected_negative = group == "checker-negative-contract"
        require(row.get("expected_negative") is expected_negative and
                case.get("expected_negative") is expected_negative,
                "negative/positive classification changed: " + path)
        if expected_negative:
            negative_count += 1
        else:
            positive_count += 1
            if candidates:
                positive_compiled += 1
            else:
                positive_interpreter_only += 1
        if not case["main_marker"]:
            non_main += 1

    require((negative_count, positive_count, positive_compiled,
             positive_interpreter_only, non_main) == (9, 13, 11, 2, 4),
            "RUN-SPEC exact contract partition changed")
    require({
        group: sum(record["contract_group"] == group for record in pending_records)
        for group in PENDING_CONTRACT_COUNTS
    } == PENDING_CONTRACT_COUNTS, "pending contract-group counts changed")

    v104_audit = parse_json(captured["v104_audit"], "v104 historical audit")
    for flag in ("manifest_integrity_passed", "frozen_selection_binding_validated",
                 "621_original_completed_bindings_validated",
                 "raw_streams_and_output_hashes_verified",
                 "runtime_byte_oracles_verified", "default_C_parity_verified"):
        require(v104_audit.get(flag) is True, "v104 audit claim absent: " + flag)
    audited_cases = v104_audit.get("cases")
    require(isinstance(audited_cases, list) and len(audited_cases) == 87,
            "v104 audit case scope changed")
    require([case.get("path") for case in audited_cases] == old_paths,
            "v104 audit original order changed")
    require(all(case.get("status") == record["status"] and
                case.get("stage_count") == len(record["stages"])
                for case, record in zip(audited_cases, records)),
            "v104 audit classification/stage scope changed")
    require(v104_audit.get("stage_receipts_verified") ==
            sum(len(record["stages"]) for record in records),
            "v104 audit receipt count changed")

    terminal_audit = copy.deepcopy(
        old_selection["audited_ancestry"]["artifacts"]["terminal_audit"]
    )
    require(
        terminal_audit["sha256"] == old_policy.pins["ancestry_terminal_audit"],
        "v104/historical terminal audit pin differs from validated ancestry",
    )

    reviewed_source_pins = {
        role: {"path": relative, "sha256": source_pins[role]}
        for role, relative in PHYSICAL_SOURCE_PINS.items()
    }
    reviewed_source_pins["accepted_projection"] = {
        "sha256": source_pins["accepted_projection"]
    }

    selection = {
        "schema": SELECTION_SCHEMA,
        "purpose": "next-safe100",
        "execution_authorized": False,
        "resume_authorized": False,
        "proposal_only": True,
        "selection": pending_paths,
        "source_sha256_by_path": projection["source_sha256_by_path"],
        "contract_groups_by_path": projection["original_contract_groups_by_path"],
        "baseline_row_sha256_by_path": projection[
            "original_baseline_row_sha256_by_path"
        ],
        "old_ancestry": {
            "old_selection": {
                "path": OLD_SELECTION_REL,
                "sha256": source_pins["old_selection"],
            },
            "old_closed_manifest": {
                "path": OLD_RESULT_REL + "/DELTA.json",
                "file_sha256": source_pins["old_manifest"],
                "manifest_internal_checksum_sha256": projection[
                    "old_manifest_ancestry"
                ]["manifest_internal_checksum_sha256"],
            },
            "accepted_projection_sha256": source_pins["accepted_projection"],
            "historical_terminal_audit": terminal_audit,
            "v104_audit": {"path": PHYSICAL_SOURCE_PINS["v104_audit"],
                           "sha256": source_pins["v104_audit"]},
            "old_terminal_case_count": 65,
            "old_pending_case_count": 22,
            "historical_reference_only": True,
        },
        "fresh_execution_policy": {
            "exact_case_count": 22,
            "fresh_stage_names": [],
            "fresh_receipt_objects": [],
            "historical_stage_objects_transferred": False,
            "op_let_requires_complete_fresh_run": True,
            "compiled_c_pass_promised": False,
            "gpu_dispatches": 0,
            "execution_wall_seconds": 600,
        },
        "source_pins": reviewed_source_pins,
        "run_spec": {
            "path": RUN_SPEC_REL,
            "sha256": source_pins["run_spec"],
        },
        "resource_hold_anchor": copy.deepcopy(old_selection["resource_hold_anchor"]),
        "partial_receipt_reuse_policy": "none-fresh-case-execution",
        "pressure_qualification_required": True,
    }

    if prepare_selection:
        require(selection_sha256 is None, "selection generation cannot reuse an input pin")
        selection_raw = encode(selection)
    else:
        selection_path = root / NEW_SELECTION_REL
        selection_raw, _ = read_pinned(
            selection_path, require_hash(selection_sha256, "new selection"),
            65536, "new pending22 selection",
        )
        require(parse_json(selection_raw, "new pending22 selection") == selection,
                "reviewed selection differs from recomputed exact old pending22")

    return {
        "selection": selection,
        "selection_file_sha256": digest(selection_raw),
        "accepted_projection_sha256": source_pins["accepted_projection"],
        "old_terminal_paths_sha256": digest(encode(terminal_paths)),
        "old_pending_paths_sha256": digest(encode(pending_paths)),
    }

