#!/usr/bin/env python3
"""Turn a JSON fixture into a Fe module of constants.

`fe test` has no I/O, so a fixture cannot be read at test time: it has to be
Fe source. This writes that source.

    python3 tools/fixture_to_fe.py fixtures/recent_fulu.json

It emits `verife/src/fixture_<name>.fe`, which is generated and committed --
committed because the test suite needs it, generated because nobody should be
hand-copying 19 sibling hashes.

The output is deliberately typed rather than flat. A branch becomes a
`RecentProof<Fulu>` or a `PayloadProof<Fulu>`, not a bare array, so the fixture
meets the same compiler check the verifier's own callers do: if the generator
emitted a 19-level branch for a fork whose recent proof is 18 levels, the
generated file would not compile. The fixture is therefore type-checked against
the layout it claims to come from, on top of being hash-checked by
`fixture_check.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Fork name in a fixture -> the Fe layout type.
FORK_TYPE = {"capella": "Capella", "deneb": "Deneb", "electra": "Electra", "fulu": "Fulu"}

PAYLOAD_FIELDS = [
    ("state_root", "state_root_proof", "u256"),
    ("receipts_root", "receipts_root_proof", "u256"),
    ("block_number", "block_number_proof", "u64"),
    ("timestamp", "timestamp_proof", "u64"),
    ("block_hash", "block_hash_proof", "u256"),
]


def gindex_crosscheck(target_fork: str, anchor_fork: str, proofs: dict,
                      extras: list[tuple[str, str]]) -> str:
    """`static_assert`s pinning the generator's gindices to the verifier's.

    This is the cross-check `gen_fixture.mjs` says it provides and, until now,
    did not: it wrote `expected_gindex` into the fixture so "a mismatch between
    this tool and the Fe side is a loud failure rather than a silent one", and
    nothing ever compared the two. The value reached a doc comment and stopped.

    The two derivations are genuinely independent and must stay that way. The
    generator reads its positions from `@lodestar/types`, which hand-writes the
    consensus containers in TypeScript; the verifier computes its own from
    field counts with `const fn`. Making the generator import the verifier's
    positions would remove a real check rather than add one.

    So they are compared instead -- and because both sides are constants, the
    comparison is a `static_assert`. A disagreement about where a field sits
    does not fail a test; it fails the build.
    """
    lines = []
    for name, _fn, _kind in PAYLOAD_FIELDS:
        if name not in proofs:
            continue
        upper = name.upper()
        lines.append(
            f"/// What the verifier derives for `{name}` from `{target_fork}`.\n"
            f"const DERIVED_{upper}_GINDEX: u64 =\n"
            f"    payload_field_gindex<{target_fork}>(field: PAYLOAD_{upper}_FIELD)\n"
            f"static_assert(PAYLOAD_{upper}_GINDEX == DERIVED_{upper}_GINDEX)"
        )
    for const_name, expr in extras:
        lines.append(
            f"const DERIVED_{const_name}: u64 = {expr}\n"
            f"static_assert({const_name} == DERIVED_{const_name})"
        )
    if not lines:
        return ""
    return ("\n// --- The generator's positions, against the verifier's -----------------------\n"
            "//\n"
            "// Left of each `==`: what `@lodestar/types` computed, carried in the fixture.\n"
            "// Right: what this library derives from the layout type with `const fn`.\n"
            "//\n"
            "// Two independent derivations of the same number, compared at COMPILE TIME.\n"
            "// A disagreement stops the build rather than failing a test, and neither side\n"
            "// can drift toward the other because they share no code: lodestar hand-writes\n"
            "// the consensus containers in TypeScript, this library computes positions from\n"
            "// field counts.\n"
            "//\n"
            "// The intermediate `DERIVED_*` consts exist so each `static_assert` fits on one\n"
            "// line. `fe fmt` wraps a longer one and adds a trailing comma that `fe check`\n"
            "// then rejects -- see docs/fe-findings.md.\n\n"
            + "\n\n".join(lines) + "\n")


def branch_literal(branch: list[str], indent: str = "        ") -> str:
    """A `[u256; N]` literal, one sibling per line so a diff is readable."""
    lines = [f"{indent}{value}," for value in branch]
    return "[\n" + "\n".join(lines) + f"\n{indent[:-4]}]"


def header_fn(name: str, header: dict, doc: str) -> str:
    return f'''/// {doc}
pub fn {name}() -> BeaconBlockHeader {{
    BeaconBlockHeader {{
        slot: {header["slot"]},
        proposer_index: {header["proposer_index"]},
        parent_root: {header["parent_root"]},
        state_root: {header["state_root"]},
        body_root: {header["body_root"]},
    }}
}}'''


def render(fixture: dict, source: str) -> str:
    anchor = fixture["anchor"]
    target = fixture["target"]
    anchor_fork = FORK_TYPE[anchor["fork"]]
    target_fork = FORK_TYPE[target["fork"]]
    values = target["payload"]["values"]
    proofs = target["payload"]["proofs"]
    provenance = fixture["provenance"]
    eip4788 = anchor["eip4788"]

    imports = sorted({anchor_fork, target_fork} | {
        "ForkVersionProof", "PayloadProof", "RecentProof",
        "block_root_gindex", "fork_version_gindex",
        "PAYLOAD_STATE_ROOT_FIELD", "PAYLOAD_RECEIPTS_ROOT_FIELD", "PAYLOAD_BLOCK_NUMBER_FIELD", "PAYLOAD_TIMESTAMP_FIELD", "PAYLOAD_BLOCK_HASH_FIELD", "payload_field_gindex",
    })

    parts = [
        f'''//! GENERATED by `tools/fixture_to_fe.py` from `{source}`. Do not edit.
//!
//! Real mainnet data: a {anchor["fork"]} anchor at slot {anchor["slot"]:,} and a
//! {target["fork"]} target at slot {target["slot"]:,}, on the recent path
//! (`block_roots[{target["block_roots"]["index"]}]`).
//!
//! Provenance, as the fixture records it:
//!
//!   * anchor state from `{provenance["state_endpoint"]}`
//!     on {provenance["generated_at"]}, SHA-256 of the raw SSZ
//!     `{provenance["state_ssz_sha256"][:26]}…` ({provenance["state_ssz_bytes"]:,} bytes)
//!   * headers and blocks from `{provenance["beacon_api"]}`
//!   * the anchor root is what the EIP-4788 contract at
//!     `{eip4788["contract"]}` returns for timestamp
//!     {eip4788["timestamp"]}, confirmed by `eth_call`: {str(eip4788["matches_anchor_root"]).lower()}
//!   * gindices derived from consensus-specs {provenance["consensus_specs"]} and
//!     cross-checked against @lodestar/types {provenance["lodestar_types"]}
//!
//! Every root here is re-derived from `hashlib` alone by
//! `tools/fixture_check.py` before the fixture is committed, and re-derived
//! again by Fe in `verify.fe`'s tests. Nothing in this file is trusted: the
//! anchor root is the one input a verification starts from, and the rest has to
//! hash back to it.

use ingot::header::BeaconBlockHeader
use ingot::layout::{{{", ".join(imports)}}}

/// The EIP-4788 timestamp whose parent beacon block root is the anchor root.
pub const ANCHOR_TIMESTAMP: u64 = {eip4788["timestamp"]}

/// The one trusted input: the beacon block root the EIP-4788 contract returns.
pub const ANCHOR_ROOT: u256 = {anchor["root"]}

/// The anchor block's slot.
pub const ANCHOR_SLOT: u64 = {anchor["slot"]}

/// The anchor state root, which every state-side branch is proven against.
pub const ANCHOR_STATE_ROOT: u256 = {anchor["state_root"]}

/// The target slot this fixture proves.
pub const TARGET_SLOT: u64 = {target["slot"]}

/// The target block's root, which `block_roots` commits to.
pub const TARGET_ROOT: u256 = {target["root"]}

/// The target block's body root, where the execution payload hangs.
pub const TARGET_BODY_ROOT: u256 = {target["header"]["body_root"]}

/// The index of the target slot in `block_roots`: `slot mod 8192`.
pub const BLOCK_ROOTS_INDEX: u64 = {target["block_roots"]["index"]}

/// Lodestar's positions for the state-side legs, pinned below.
pub const BLOCK_ROOTS_GINDEX: u64 = {target["block_roots"]["expected_gindex"]}
pub const FORK_VERSION_GINDEX: u64 = {anchor["fork_version"]["expected_gindex"]}''',
        header_fn(
            "anchor_header",
            anchor["header"],
            "The anchor header, whose five fields hash to `ANCHOR_ROOT`.",
        ),
        header_fn(
            "target_header",
            target["header"],
            "The target header, whose five fields hash to `TARGET_ROOT`.",
        ),
        f'''/// `block_roots[{target["block_roots"]["index"]}]` out of the anchor state: {len(target["block_roots"]["branch"])} levels, which is
/// `block_root_proof_len<{anchor_fork}>()`. The compiler checks that count here.
pub fn recent_proof() -> RecentProof<{anchor_fork}> {{
    RecentProof<{anchor_fork}> {{
        branch: {branch_literal(target["block_roots"]["branch"])},
    }}
}}''',
        f'''/// `state.fork.current_version` out of the anchor state (invariant 8):
/// {len(anchor["fork_version"]["branch"])} levels.
pub fn fork_version_proof() -> ForkVersionProof<{anchor_fork}> {{
    ForkVersionProof<{anchor_fork}> {{
        branch: {branch_literal(anchor["fork_version"]["branch"])},
    }}
}}''',
    ]

    for name, fn, kind in PAYLOAD_FIELDS:
        value = values[name]
        literal = value if kind == "u256" else str(value)
        parts.append(
            f'''/// The target payload's `{name}`.
pub const PAYLOAD_{name.upper()}: {kind} = {literal}

/// What `@lodestar/types` computed for this position. Pinned against the
/// verifier's own derivation by a `static_assert` at the end of this file.
pub const PAYLOAD_{name.upper()}_GINDEX: u64 = {proofs[name]["expected_gindex"]}

/// `execution_payload.{name}` out of the target body root: gindex
/// {proofs[name]["expected_gindex"]}, {len(proofs[name]["branch"])} levels.
pub fn {fn}() -> PayloadProof<{target_fork}> {{
    PayloadProof<{target_fork}> {{
        branch: {branch_literal(proofs[name]["branch"])},
    }}
}}'''
        )

    extras = [
        ("BLOCK_ROOTS_GINDEX",
         f"block_root_gindex<{anchor_fork}>(index: BLOCK_ROOTS_INDEX)"),
        ("FORK_VERSION_GINDEX", f"fork_version_gindex<{anchor_fork}>()"),
    ]
    body = "\n\n".join(parts) + "\n"
    return body + gindex_crosscheck(target_fork, anchor_fork, proofs, extras)


def render_historical(fixture: dict, source: str) -> str:
    """A historical-path fixture: an anchor fork and a target fork that differ."""
    anchor = fixture["anchor"]
    target = fixture["target"]
    anchor_fork = FORK_TYPE[anchor["fork"]]
    target_fork = FORK_TYPE[target["fork"]]
    summary = target["summary"]
    period = target["period"]
    values = target["payload"]["values"]
    proofs = target["payload"]["proofs"]
    provenance = fixture["provenance"]
    rebuild = provenance["period_rebuild"]
    eip4788 = anchor["eip4788"]

    imports = sorted({anchor_fork, target_fork} | {
        "HistoricalProof", "PayloadProof",
        "historical_summaries_length_gindex", "summary_block_root_gindex",
        "PAYLOAD_STATE_ROOT_FIELD", "PAYLOAD_RECEIPTS_ROOT_FIELD", "PAYLOAD_BLOCK_NUMBER_FIELD", "PAYLOAD_TIMESTAMP_FIELD", "PAYLOAD_BLOCK_HASH_FIELD", "payload_field_gindex",
    })

    parts = [
        f'''//! GENERATED by `tools/fixture_to_fe.py` from `{source}`. Do not edit.
//!
//! The historical path on real mainnet data, across a fork boundary: a
//! **{anchor["fork"]}** anchor at slot {anchor["slot"]:,} proving a **{target["fork"]}** target at
//! slot {target["slot"]:,} -- {(anchor["slot"] - target["slot"]):,} slots earlier, about
//! {round((anchor["slot"] - target["slot"]) * 12 / 86400)} days, far outside the ~27-hour EIP-4788 window.
//!
//! The target is slot {target["slot"]:,}, the **first Capella block**: Capella's own
//! first slot ({target["slot"] - 2:,}) and the one after it were both missed, so the
//! chain's first post-Capella block is two slots late. Its summary index is
//! {summary["index"]} -- the first entry `historical_summaries` ever had.
//!
//! The path runs: anchor header -> `historical_summaries` length mix-in
//! (invariant 4) -> `historical_summaries[{summary["index"]}].block_summary_root`
//! ({len(summary["branch"])} levels) -> the period's `Vector[Root, 8192]`
//! ({len(period["branch"])} levels) -> the target header -> its payload fields
//! ({len(proofs["block_hash"]["branch"])} levels, Capella's shallower payload).
//!
//! The period vector was rebuilt from {rebuild["last_slot"] - rebuild["first_slot"] + 1:,} block roots
//! (slots {rebuild["first_slot"]:,}..{rebuild["last_slot"]:,}, of which {rebuild["missed_slots"]} were missed and carry the
//! previous root forward), and was used **only** because it hashes to the
//! `block_summary_root` the anchor state commits to.
//!
//! Provenance: anchor state from `{provenance["state_endpoint"]}`
//! on {provenance["generated_at"]} (SHA-256 `{provenance["state_ssz_sha256"][:26]}…`); headers and
//! blocks from `{provenance["beacon_api"]}`; the anchor root is what the
//! EIP-4788 contract returns for timestamp {eip4788["timestamp"]}, confirmed by
//! `eth_call`: {str(eip4788["matches_anchor_root"]).lower()}.

use ingot::header::BeaconBlockHeader
use ingot::layout::{{{", ".join(imports)}}}

/// The one trusted input.
pub const ANCHOR_ROOT: u256 = {anchor["root"]}

/// The anchor block's slot.
pub const ANCHOR_SLOT: u64 = {anchor["slot"]}

/// The anchor state root every branch is proven against.
pub const ANCHOR_STATE_ROOT: u256 = {anchor["state_root"]}

/// The target slot: the first Capella block.
pub const TARGET_SLOT: u64 = {target["slot"]}

/// Its block root.
pub const TARGET_ROOT: u256 = {target["root"]}

/// Its body root, where the execution payload hangs.
pub const TARGET_BODY_ROOT: u256 = {target["header"]["body_root"]}

/// The summary index this slot implies: `slot / 8192 - 758`.
pub const SUMMARY_INDEX: u64 = {summary["index"]}

/// The `historical_summaries` length the anchor state commits to.
pub const SUMMARY_LENGTH: u64 = {summary["length"]}

/// The period vector's root, as `historical_summaries[{summary["index"]}].block_summary_root`.
pub const BLOCK_SUMMARY_ROOT: u256 = {summary["block_summary_root"]}

/// Lodestar's positions for the two summary legs, pinned below.
pub const SUMMARY_GINDEX: u64 = {summary["expected_gindex"]}
pub const SUMMARY_LENGTH_GINDEX: u64 = {summary["length_expected_gindex"]}

/// The target slot's index within its period: `slot mod 8192`.
pub const INDEX_IN_PERIOD: u64 = {period["index_in_period"]}''',
        header_fn(
            "anchor_header",
            anchor["header"],
            "The anchor header, whose five fields hash to `ANCHOR_ROOT`.",
        ),
        header_fn(
            "target_header",
            target["header"],
            "The target header, whose five fields hash to `TARGET_ROOT`.",
        ),
        f'''/// The three branches of the historical path, each its own derived length:
/// the summary at gindex {summary["expected_gindex"]} ({len(summary["branch"])} levels), the length
/// mix-in at gindex {summary["length_expected_gindex"]} ({len(summary["length_branch"])} levels), and the
/// period vector ({len(period["branch"])} levels, fork-independent).
pub fn historical_proof() -> HistoricalProof<{anchor_fork}> {{
    HistoricalProof<{anchor_fork}> {{
        index: {summary["index"]},
        length: {summary["length"]},
        summary_branch: {branch_literal(summary["branch"], "            ")},
        length_branch: {branch_literal(summary["length_branch"], "            ")},
        period_branch: {branch_literal(period["branch"], "            ")},
    }}
}}''',
    ]

    for name, fn, kind in PAYLOAD_FIELDS:
        value = values[name]
        literal = value if kind == "u256" else str(value)
        parts.append(
            f'''/// The target payload's `{name}`.
pub const PAYLOAD_{name.upper()}: {kind} = {literal}

/// What `@lodestar/types` computed for this position. Pinned against the
/// verifier's own derivation by a `static_assert` at the end of this file.
pub const PAYLOAD_{name.upper()}_GINDEX: u64 = {proofs[name]["expected_gindex"]}

/// `execution_payload.{name}` out of the target body root: gindex
/// {proofs[name]["expected_gindex"]}, {len(proofs[name]["branch"])} levels. Note the layout parameter is the
/// **target's** ({target_fork}), not the anchor's.
pub fn {fn}() -> PayloadProof<{target_fork}> {{
    PayloadProof<{target_fork}> {{
        branch: {branch_literal(proofs[name]["branch"])},
    }}
}}'''
        )

    extras = [
        ("SUMMARY_GINDEX",
         f"summary_block_root_gindex<{anchor_fork}>(index: SUMMARY_INDEX)"),
        ("SUMMARY_LENGTH_GINDEX",
         f"historical_summaries_length_gindex<{anchor_fork}>()"),
    ]
    body = "\n\n".join(parts) + "\n"
    return body + gindex_crosscheck(target_fork, anchor_fork, proofs, extras)


def render_missed(fixture: dict, source: str) -> str:
    """A missed-slot fixture: the input that makes invariant 10 necessary."""
    anchor = fixture["anchor"]
    claim = fixture["claim"]
    anchor_fork = FORK_TYPE[anchor["fork"]]
    provenance = fixture["provenance"]
    eip4788 = anchor["eip4788"]

    return f'''//! GENERATED by `tools/fixture_to_fe.py` from `{source}`. Do not edit.
//!
//! The missed-slot attack, with real mainnet data.
//!
//! Slot {claim["claimed_slot"]:,} was **missed**: no block was proposed. The beacon
//! chain's `process_slot` therefore wrote the previous block's root into
//! `block_roots[{claim["block_roots"]["index"]}]` a second time, so that one entry is the root of
//! slot {claim["repeated_header_slot"]:,} and two slots map to it.
//!
//! A prover can now present everything a verifier asks for: a genuinely valid
//! {len(claim["block_roots"]["branch"])}-level branch, at the gindex that really is correct for the slot
//! being claimed, carrying a header that really is in `block_roots`. The anchor
//! header hashes to the anchor root, the branch reaches the anchor state root,
//! the index is `slot mod 8192`. Every check passes but one:
//! `header.slot == s` -- security invariant 10 -- because the header says slot
//! {claim["repeated_header_slot"]:,} and the claim says {claim["claimed_slot"]:,}.
//!
//! This is the recent-path cousin of the Lido 2025 bug: the node exists, the
//! branch is real, and only an exact-position check stands in the way. The
//! anchor state's own `block_roots` named 33 missed slots in its window; this
//! is one of them.
//!
//! Provenance: anchor state from `{provenance["state_endpoint"]}`
//! on {provenance["generated_at"]} (SHA-256 `{provenance["state_ssz_sha256"][:26]}…`); headers from
//! `{provenance["beacon_api"]}`; the anchor root is what the EIP-4788
//! contract returns for timestamp {eip4788["timestamp"]}, confirmed by `eth_call`:
//! {str(eip4788["matches_anchor_root"]).lower()}.

use ingot::header::BeaconBlockHeader
use ingot::layout::{{{anchor_fork}, RecentProof}}

/// The one trusted input.
pub const ANCHOR_ROOT: u256 = {anchor["root"]}

/// The anchor block's slot.
pub const ANCHOR_SLOT: u64 = {anchor["slot"]}

/// The anchor state root the branch is proven against.
pub const ANCHOR_STATE_ROOT: u256 = {anchor["state_root"]}

/// The slot being claimed, which was missed.
pub const CLAIMED_SLOT: u64 = {claim["claimed_slot"]}

/// The slot whose root `block_roots` actually holds at that index.
pub const REPEATED_HEADER_SLOT: u64 = {claim["repeated_header_slot"]}

/// `claimed_slot mod 8192`, the index the repeated root sits at.
pub const BLOCK_ROOTS_INDEX: u64 = {claim["block_roots"]["index"]}

/// The root `block_roots` holds there: the repeated header's own root.
pub const REPEATED_HEADER_ROOT: u256 = {claim["repeated_header_root"]}

{header_fn("anchor_header", anchor["header"], "The anchor header, which hashes to `ANCHOR_ROOT`.")}

{header_fn("repeated_header", claim["repeated_header"], "The header `block_roots` really holds: slot " + format(claim["repeated_header_slot"], ",") + ", not the claimed slot.")}

/// A real branch, at the correct gindex for the *claimed* slot
/// (gindex {claim["block_roots"]["expected_gindex"]}), carrying the repeated header's root.
pub fn recent_proof() -> RecentProof<{anchor_fork}> {{
    RecentProof<{anchor_fork}> {{
        branch: {branch_literal(claim["block_roots"]["branch"])},
    }}
}}
'''


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    fixture = json.loads(source.read_text())
    kind = fixture.get("kind")
    if kind not in ("recent", "historical", "missed_slot"):
        print(f"unsupported fixture kind {kind!r}")
        return 1

    out = (
        Path(__file__).resolve().parent.parent
        / "verife"
        / "src"
        / f"fixture_{source.stem}.fe"
    )
    renderers = {
        "recent": render,
        "historical": render_historical,
        "missed_slot": render_missed,
    }
    body = renderers[kind](fixture, source=source.as_posix())
    out.write_text(body)
    print(f"wrote {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    print("  run `fe fmt` in verife/ and then the tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
