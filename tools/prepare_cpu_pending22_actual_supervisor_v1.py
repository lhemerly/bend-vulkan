"""Source-only exact-pin and fresh-delta rebind; never creates authorization."""

import argparse
import hashlib
import json
import os
import re
import types
from pathlib import Path


HASH = re.compile(r"^[0-9a-f]{64}$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_hash(value, label):
    require(HASH.fullmatch(value) is not None, label + " must be SHA256")
    return value


def prepare(
    template,
    template_sha256,
    manifest,
    output,
    runner_sha256,
    adapter_sha256,
    validator_sha256,
    storage_sha256,
    old_selection_sha256,
    old_manifest_sha256,
    selection_sha256,
    overlay_sha256,
    run_spec_sha256,
    accepted_projection_sha256,
    delta_sha256,
):
    template = Path(template).resolve()
    manifest = Path(manifest).resolve()
    output = Path(output).resolve()
    raw = template.read_bytes()
    require_hash(template_sha256, "template SHA256")
    require(hashlib.sha256(raw).hexdigest() == template_sha256,
            "reviewed supervisor template changed")

    replacements = {
        "__PENDING22_RUNNER_SHA256__": require_hash(runner_sha256, "runner"),
        "__PENDING22_ADAPTER_SHA256__": require_hash(adapter_sha256, "adapter"),
        "__PENDING22_VALIDATOR_SHA256__": require_hash(validator_sha256, "validator"),
        "__PENDING22_STORAGE_SHA256__": require_hash(storage_sha256, "storage"),
        "__PENDING22_OLD_SELECTION_SHA256__": require_hash(
            old_selection_sha256, "old selection"
        ),
        "__PENDING22_OLD_MANIFEST_SHA256__": require_hash(
            old_manifest_sha256, "old manifest"
        ),
        "__PENDING22_SELECTION_SHA256__": require_hash(
            selection_sha256, "new selection"
        ),
        "__PENDING22_OVERLAY_SHA256__": require_hash(overlay_sha256, "overlay"),
        "__PENDING22_RUN_SPEC_SHA256__": require_hash(run_spec_sha256, "RUN-SPEC"),
        "__PENDING22_ACCEPTED_PROJECTION_SHA256__": require_hash(
            accepted_projection_sha256, "accepted projection"
        ),
        "__PENDING22_DELTA_SHA256__": require_hash(delta_sha256, "fresh delta"),
    }
    generated = raw.decode("utf-8")
    for token, value in replacements.items():
        require(generated.count(token) == 1,
                "template placeholder must occur exactly once: " + token)
        generated = generated.replace(token, value)
    require("__PENDING22_" not in generated, "unreplaced supervisor placeholder")

    module = types.ModuleType("_reviewed_pending22_supervisor_generated")
    module.__file__ = str(template)
    module.__package__ = ""
    module.__cached__ = None
    exec(compile(generated, str(template), "exec"), module.__dict__)
    require(module.ROOT == template.parents[1],
            "generated supervisor changed project ROOT")
    require(manifest == module.E / module.OUTPUT_NAME / "DELTA.json",
            "wrong fresh exact22 manifest")
    require(
        (module.RUNNER_SHA, module.ADAPTER_SHA, module.VALIDATOR_SHA,
         module.STORAGE_SHA, module.OLD_SELECTION_SHA, module.OLD_MANIFEST_SHA,
         module.SELECTION_SHA, module.OVERLAY_SHA, module.RUN_SPEC_SHA,
         module.ACCEPTED_PROJECTION_SHA, module.DELTA_SHA)
        == tuple(replacements[token] for token in (
            "__PENDING22_RUNNER_SHA256__",
            "__PENDING22_ADAPTER_SHA256__",
            "__PENDING22_VALIDATOR_SHA256__",
            "__PENDING22_STORAGE_SHA256__",
            "__PENDING22_OLD_SELECTION_SHA256__",
            "__PENDING22_OLD_MANIFEST_SHA256__",
            "__PENDING22_SELECTION_SHA256__",
            "__PENDING22_OVERLAY_SHA256__",
            "__PENDING22_RUN_SPEC_SHA256__",
            "__PENDING22_ACCEPTED_PROJECTION_SHA256__",
            "__PENDING22_DELTA_SHA256__",
        )),
        "generated supervisor constants differ from reviewed replacements",
    )
    supervisor_sha = digest(template)
    pins = module.physical_pins(supervisor_sha)
    module.verify_inputs(pins)
    delta = module.read_prepared_delta(manifest, module.ROOT / module.RUNNER_REL)
    require(len(delta["records"]) == 22 and
            all(row["status"] == "pending" and row["stages"] == {}
                for row in delta["records"]),
            "fresh exact22 empty records required")

    require(output.parent == template.parent,
            "bound supervisor must remain under the original project tools directory")
    descriptor = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(generated.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "supervisor_sha256": digest(output),
        "delta_sha256": delta_sha256,
        "prepared_records": 22,
        "all_records_pending_empty": True,
        "execution_authorized": False,
        "grant_created": False,
        "policy_created": False,
        "reservation_created": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runner-sha256", required=True)
    parser.add_argument("--adapter-sha256", required=True)
    parser.add_argument("--validator-sha256", required=True)
    parser.add_argument("--storage-sha256", required=True)
    parser.add_argument("--old-selection-sha256", required=True)
    parser.add_argument("--old-manifest-sha256", required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--overlay-sha256", required=True)
    parser.add_argument("--run-spec-sha256", required=True)
    parser.add_argument("--accepted-projection-sha256", required=True)
    parser.add_argument("--delta-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(**vars(args)), indent=2))


if __name__ == "__main__":
    main()
