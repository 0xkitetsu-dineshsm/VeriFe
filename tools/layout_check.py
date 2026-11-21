#!/usr/bin/env python3
"""Derive VeriFe's layout numbers from the consensus specs and check them.

This is the tool behind open question 1: every field count, field position and
generalized index that `verife/src/layout.fe` pins with `static_assert` has to
come from the specs, not from memory. It reads the container definitions out of
`consensus-specs` itself, resolves each fork's effective containers (a fork
redefines a container in full, so the latest definition at or before a fork
wins), derives the gindices with the same arithmetic `verife/src/gindex.fe`
uses, and compares the result with the table this repository has been working
from.

Usage:

    python3 tools/layout_check.py                # check against the table
    python3 tools/layout_check.py --print        # just print what the specs say
    python3 tools/layout_check.py --tag v1.6.1   # pin a different spec release

Exits non-zero on any mismatch, so CI can run it. Specs are cached under
`tools/cache/specs/<tag>/` (gitignored); pass `--refresh` to re-download.

Not Fe, and not part of the contest's core contribution: it is a check on the
Fe source, declared as such in the README.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

# Forks in order. A container defined in a later fork replaces the earlier
# definition wholesale, which is how the specs are written.
FORKS = ["phase0", "altair", "bellatrix", "capella", "deneb", "electra", "fulu"]

# The forks VeriFe implements layouts for.
TARGET_FORKS = ["capella", "deneb", "electra", "fulu"]

SPEC_FILES = [f"{fork}/beacon-chain.md" for fork in FORKS]
RAW = "https://raw.githubusercontent.com/ethereum/consensus-specs/{tag}/specs/{path}"

CLASS_RE = re.compile(r"^class\s+(\w+)\(Container\):\s*$")
FIELD_RE = re.compile(r"^\s{4}(\w+)\s*:\s*([^#]+?)\s*(?:#.*)?$")

# What the working table in CLAUDE.md claims. The point of this script is to
# agree or disagree with it, loudly.
EXPECTED = {
    "capella": {
        "state_fields": 28,
        "block_roots_gi": 37,
        "historical_summaries_gi": 59,
        "body_fields": 11,
        "payload_fields": 15,
        "payload_state_root_gi": 18,
    },
    "deneb": {
        "state_fields": 28,
        "block_roots_gi": 37,
        "historical_summaries_gi": 59,
        "body_fields": 12,
        "payload_fields": 17,
        "payload_state_root_gi": 34,
    },
    "electra": {
        "state_fields": 37,
        "block_roots_gi": 69,
        "historical_summaries_gi": 91,
        "body_fields": 13,
        "payload_fields": 17,
        "payload_state_root_gi": 34,
    },
    "fulu": {
        "state_fields": 38,
        "block_roots_gi": 69,
        "historical_summaries_gi": 91,
        "body_fields": 13,
        "payload_fields": 17,
        "payload_state_root_gi": 34,
    },
}

# Field positions the chain of commitments walks through, as names rather than
# numbers: the whole point is that the numbers are derived.
STATE_FIELDS = ["fork", "block_roots", "historical_summaries"]
PAYLOAD_FIELDS = [
    "state_root",
    "receipts_root",
    "block_number",
    "timestamp",
    "block_hash",
]


def depth(leaves: int) -> int:
    """ceil(log2(leaves)) -- `gindex.fe`'s `depth`, as a check on it."""
    out = 0
    while (1 << out) < leaves:
        out += 1
    return out


def field_gindex(field: int, field_count: int) -> int:
    assert field < field_count, (field, field_count)
    return (1 << depth(field_count)) + field


def concat(outer: int, inner: int) -> int:
    """`gindex.fe`'s `concat`: splice `inner` under `outer`."""
    inner_depth = inner.bit_length() - 1
    return outer * (1 << inner_depth) + (inner - (1 << inner_depth))


def fetch(tag: str, cache: Path, refresh: bool) -> dict[str, str]:
    out = {}
    for path in SPEC_FILES:
        local = cache / tag / path
        if refresh or not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            url = RAW.format(tag=tag, path=path)
            with urllib.request.urlopen(url, timeout=60) as response:
                local.write_bytes(response.read())
        out[path.split("/")[0]] = local.read_text()
    return out


def containers(markdown: str) -> dict[str, list[str]]:
    """Every `class X(Container)` in one spec file, as a field-name list."""
    found: dict[str, list[str]] = {}
    name = None
    fields: list[str] = []
    for line in markdown.splitlines():
        match = CLASS_RE.match(line)
        if match:
            if name:
                found[name] = fields
            name, fields = match.group(1), []
            continue
        if name is None:
            continue
        if not line.strip() or line.startswith("```"):
            if fields:
                found[name] = fields
            name, fields = None, []
            continue
        field = FIELD_RE.match(line)
        if field:
            fields.append(field.group(1))
    if name and fields:
        found[name] = fields
    return found


def effective(per_fork: dict[str, dict[str, list[str]]], upto: str) -> dict[str, list[str]]:
    """The containers in force at `upto`: later definitions override earlier."""
    out: dict[str, list[str]] = {}
    for fork in FORKS[: FORKS.index(upto) + 1]:
        out.update(per_fork[fork])
    return out


def layout(defs: dict[str, list[str]]) -> dict[str, object]:
    state = defs["BeaconState"]
    body = defs["BeaconBlockBody"]
    payload = defs["ExecutionPayload"]
    header = defs["BeaconBlockHeader"]
    fork_container = defs["Fork"]
    summary = defs["HistoricalSummary"]

    out: dict[str, object] = {
        "state_fields": len(state),
        "state_depth": depth(len(state)),
        "body_fields": len(body),
        "body_depth": depth(len(body)),
        "payload_fields": len(payload),
        "payload_depth": depth(len(payload)),
        "header_fields": len(header),
        "fork_fields": len(fork_container),
        "fork_current_version_index": fork_container.index("current_version"),
        "summary_fields": len(summary),
        "summary_block_root_index": summary.index("block_summary_root"),
    }
    for name in STATE_FIELDS:
        out[f"{name}_index"] = state.index(name)
        out[f"{name}_gi"] = field_gindex(state.index(name), len(state))
    out["execution_payload_index"] = body.index("execution_payload")
    out["execution_payload_gi"] = field_gindex(body.index("execution_payload"), len(body))
    for name in PAYLOAD_FIELDS:
        out[f"payload_{name}_index"] = payload.index(name)
        out[f"payload_{name}_gi"] = field_gindex(payload.index(name), len(payload))
        # The composite index from the block body's root, which is what a
        # verifier actually walks: body -> execution_payload -> field.
        out[f"body_to_{name}_gi"] = concat(
            out["execution_payload_gi"], out[f"payload_{name}_gi"]
        )
    return out


def report(tag: str, layouts: dict[str, dict[str, object]], check: bool) -> int:
    print(f"consensus-specs {tag}\n")
    head = f"{'fork':<9}{'state':>7}{'depth':>7}{'fork_gi':>9}{'blk_roots':>11}{'hist_sum':>10}{'body':>6}{'payload':>9}{'pl.state_root':>15}"
    print(head)
    print("-" * len(head))
    for fork in TARGET_FORKS:
        values = layouts[fork]
        print(
            f"{fork:<9}{values['state_fields']:>7}{values['state_depth']:>7}"
            f"{values['fork_gi']:>9}{values['block_roots_gi']:>11}"
            f"{values['historical_summaries_gi']:>10}{values['body_fields']:>6}"
            f"{values['payload_fields']:>9}{values['payload_state_root_gi']:>15}"
        )

    print("\npositions (field index within its container)")
    for fork in TARGET_FORKS:
        values = layouts[fork]
        print(
            f"  {fork:<9} state: fork={values['fork_index']} "
            f"block_roots={values['block_roots_index']} "
            f"historical_summaries={values['historical_summaries_index']} | "
            f"body: execution_payload={values['execution_payload_index']} | "
            f"payload: " + " ".join(
                f"{name}={values[f'payload_{name}_index']}" for name in PAYLOAD_FIELDS
            )
        )

    print("\ngindex from the block body root to each payload field")
    for fork in TARGET_FORKS:
        values = layouts[fork]
        print(
            f"  {fork:<9} " + " ".join(
                f"{name}={values[f'body_to_{name}_gi']}" for name in PAYLOAD_FIELDS
            )
        )

    print("\nfixed across every fork VeriFe handles")
    first = layouts[TARGET_FORKS[0]]
    print(
        f"  BeaconBlockHeader fields={first['header_fields']} "
        f"depth={depth(int(first['header_fields']))} | "
        f"Fork.current_version index={first['fork_current_version_index']} "
        f"of {first['fork_fields']} | "
        f"HistoricalSummary.block_summary_root index="
        f"{first['summary_block_root_index']} of {first['summary_fields']}"
    )

    if not check:
        return 0

    print("\nchecking against the working table")
    failures = 0
    for fork in TARGET_FORKS:
        for key, want in EXPECTED[fork].items():
            got = layouts[fork][key]
            if got != want:
                failures += 1
                print(f"  MISMATCH {fork}.{key}: table says {want}, specs say {got}")
    if failures:
        print(f"\n{failures} mismatch(es). The table is wrong, or this tool is.")
        return 1
    print("  every value in the table matches the specs")
    return 0


def cross_check(layouts: dict[str, dict[str, object]]) -> int:
    """Diff the spec-derived numbers against @lodestar/types.

    A second source is the requirement, not a nicety: a parser bug in this file
    and a misreading of the spec text would both survive a check that only ever
    consults the spec text. `@lodestar/types` hand-writes the containers in
    TypeScript and `@chainsafe/ssz` walks them with its own tree code, so a
    disagreement means one of the two is wrong and neither may be trusted
    until it is resolved.
    """
    script = Path(__file__).resolve().parent / "layout_cross_check.mjs"
    try:
        completed = subprocess.run(
            ["node", str(script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=script.parent,
        )
    except FileNotFoundError:
        print("\ncross-check skipped: node is not on PATH")
        return 1
    if completed.returncode != 0:
        print("\ncross-check failed to run:")
        print((completed.stderr or completed.stdout).strip()[:800])
        print("hint: cd tools && npm install")
        return 1

    theirs = json.loads(completed.stdout)
    print("\ncross-checking against @lodestar/types")
    failures = 0
    for fork in TARGET_FORKS:
        mine = layouts[fork]
        ours = {
            "state_fields": mine["state_fields"],
            "state_fork_gi": mine["fork_gi"],
            "state_fork_current_version_gi": concat(
                int(mine["fork_gi"]),
                field_gindex(
                    int(mine["fork_current_version_index"]), int(mine["fork_fields"])
                ),
            ),
            "block_roots_gi": mine["block_roots_gi"],
            "historical_summaries_gi": mine["historical_summaries_gi"],
            "body_fields": mine["body_fields"],
            "execution_payload_gi": mine["execution_payload_gi"],
            "payload_fields": mine["payload_fields"],
            "header_fields": mine["header_fields"],
        }
        for name in PAYLOAD_FIELDS:
            ours[f"body_to_{name}_gi"] = mine[f"body_to_{name}_gi"]
        for key, want in ours.items():
            got = theirs[fork][key]
            if got != want:
                failures += 1
                print(f"  MISMATCH {fork}.{key}: specs say {want}, lodestar says {got}")
    if failures:
        print(f"\n{failures} disagreement(s) between the specs and lodestar.")
        return 1
    print("  both sources agree on every value")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="v1.6.1", help="consensus-specs git tag")
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="re-download the specs")
    parser.add_argument(
        "--cross-check",
        action="store_true",
        help="also diff against @lodestar/types (needs `cd tools && npm install`)",
    )
    args = parser.parse_args()

    cache = Path(__file__).resolve().parent / "cache" / "specs"
    sources = fetch(args.tag, cache, args.refresh)
    per_fork = {fork: containers(text) for fork, text in sources.items()}
    layouts = {fork: layout(effective(per_fork, fork)) for fork in TARGET_FORKS}
    status = report(args.tag, layouts, check=not args.print_only)
    if args.cross_check:
        status |= cross_check(layouts)
    return status


if __name__ == "__main__":
    sys.exit(main())
