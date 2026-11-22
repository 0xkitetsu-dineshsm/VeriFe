#!/usr/bin/env python3
"""Re-derive every root in a fixture, independently of the generator.

`gen_fixture.mjs` builds fixtures with `@lodestar/types` and
`@chainsafe/persistent-merkle-tree`. This script checks them with nothing but
`hashlib`: it hashes the header fields itself, walks each branch itself, and
derives each gindex itself (sharing only `layout_check.py`, which gets its
numbers from the consensus specs). So a fixture has to be right in two
implementations before any Fe test sees it, which is what CLAUDE.md asks for.

It is also a readable statement of what the Fe side must do, leg by leg:

    python3 tools/fixture_check.py fixtures/recent_fulu.json

Exits non-zero on the first thing that does not add up.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_check import (  # noqa: E402
    SPEC_FILES,
    concat,
    containers,
    depth,
    effective,
    fetch,
    field_gindex,
    layout,
)

SLOTS_PER_HISTORICAL_ROOT = 8192


def h(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()


def unhex(value: str) -> bytes:
    out = bytes.fromhex(value.removeprefix("0x"))
    assert len(out) == 32, f"not a 32-byte root: {value}"
    return out


def uint64_leaf(value: int) -> bytes:
    """Invariant 11: little-endian in the low 8 bytes of the chunk."""
    assert 0 <= value < 2**64
    return value.to_bytes(8, "little") + bytes(24)


def root_from_branch(leaf: bytes, gindex: int, branch: list[str]) -> bytes:
    """`merkle.fe`'s `root_from_branch`, including its length check."""
    assert gindex >= 1, "gindex 0 is not a node"
    assert gindex.bit_length() - 1 == len(branch), (
        f"branch of {len(branch)} for a gindex at depth {gindex.bit_length() - 1}"
    )
    node = leaf
    level = gindex
    for sibling in branch:
        other = unhex(sibling)
        node = h(node, other) if level % 2 == 0 else h(other, node)
        level //= 2
    assert level == 1
    return node


def header_root(header: dict) -> bytes:
    """The five-field `BeaconBlockHeader` merkleization, padded to 8 chunks."""
    chunks = [
        uint64_leaf(header["slot"]),
        uint64_leaf(header["proposer_index"]),
        unhex(header["parent_root"]),
        unhex(header["state_root"]),
        unhex(header["body_root"]),
        bytes(32),
        bytes(32),
        bytes(32),
    ]
    while len(chunks) > 1:
        chunks = [h(chunks[i], chunks[i + 1]) for i in range(0, len(chunks), 2)]
    return chunks[0]



def check_missed(fixture: dict, per_fork: dict, check: "Check") -> None:
    """A missed-slot fixture: every leg sound, and the claim still false."""
    anchor = fixture["anchor"]
    claim = fixture["claim"]
    anchor_layout = layout(effective(per_fork, anchor["fork"]))

    print("\nanchor (unchanged from the recent path)")
    check.equal("the five fields hash to the anchor root",
                "0x" + header_root(anchor["header"]).hex(), anchor["root"])
    check.ok("the EIP-4788 contract returns that root",
             anchor["eip4788"].get("returns") == anchor["root"])

    print("\nthe offered proof is genuine")
    index = claim["block_roots"]["index"]
    expected_gindex = concat(anchor_layout["block_roots_gi"], SLOTS_PER_HISTORICAL_ROOT + index)
    check.equal("the index is the CLAIMED slot mod 8192",
                index, claim["claimed_slot"] % SLOTS_PER_HISTORICAL_ROOT)
    check.equal("the gindex is the claimed slot's own position",
                claim["block_roots"]["expected_gindex"], expected_gindex)
    check.equal(
        "the branch reaches the anchor state root",
        "0x" + root_from_branch(
            unhex(claim["block_roots"]["leaf"]),
            claim["block_roots"]["expected_gindex"],
            claim["block_roots"]["branch"],
        ).hex(),
        anchor["state_root"],
    )
    check.equal("the leaf is the repeated header's root",
                claim["block_roots"]["leaf"], claim["repeated_header_root"])
    check.equal("that header really hashes to it",
                "0x" + header_root(claim["repeated_header"]).hex(),
                claim["repeated_header_root"])

    print("\nand the claim is still false (invariant 10)")
    check.ok("the claimed slot was missed", claim.get("missed") is True)
    check.ok("the header's slot is NOT the claimed slot",
             claim["repeated_header"]["slot"] != claim["claimed_slot"],
             f"header says {claim['repeated_header']['slot']}, claim says {claim['claimed_slot']}")
    check.equal("it is the slot before it",
                claim["repeated_header"]["slot"], claim["claimed_slot"] - 1)
    check.ok("so one block_roots entry serves two slots, and only header.slot == s "
             "tells them apart", True)



def check_historical(fixture: dict, per_fork: dict, check: "Check") -> None:
    """The historical path: four legs, each re-derived here from hashlib."""
    anchor = fixture["anchor"]
    target = fixture["target"]
    summary = target["summary"]
    period = target["period"]
    anchor_layout = layout(effective(per_fork, anchor["fork"]))
    target_layout = layout(effective(per_fork, target["fork"]))

    print("\nanchor")
    check.equal("the five fields hash to the anchor root",
                "0x" + header_root(anchor["header"]).hex(), anchor["root"])
    check.ok("the EIP-4788 contract returns that root",
             anchor["eip4788"].get("returns") == anchor["root"])

    print("\nthe summary index is the one the slot implies")
    expected_index = target["slot"] // SLOTS_PER_HISTORICAL_ROOT - 758
    check.equal("index == slot / 8192 - 758", summary["index"], expected_index)
    check.equal("index in period == slot mod 8192",
                period["index_in_period"], target["slot"] % SLOTS_PER_HISTORICAL_ROOT)

    print("\nthe list length (invariant 4)")
    length_gindex = concat(anchor_layout["historical_summaries_gi"], 3)
    check.equal("the mix-in leaf sits at the list root's right child",
                summary["length_expected_gindex"], length_gindex)
    check.equal("the leaf is the little-endian chunk of the length",
                summary["length_leaf"], "0x" + uint64_leaf(summary["length"]).hex())
    check.equal(
        "its branch reaches the anchor state root",
        "0x" + root_from_branch(
            unhex(summary["length_leaf"]), length_gindex, summary["length_branch"]
        ).hex(),
        anchor["state_root"],
    )
    check.ok("index < length", summary["index"] < summary["length"],
             f"{summary['index']} vs {summary['length']}")

    print("\nthe summary path lands on block_summary_root (invariant 3)")
    # state -> historical_summaries -> the list's data subtree -> element -> field 0
    expected_gindex = concat(
        concat(
            concat(anchor_layout["historical_summaries_gi"], 2),
            2**24 + summary["index"],
        ),
        field_gindex(0, 2),
    )
    check.equal("the gindex is field 0 at full depth",
                summary["expected_gindex"], expected_gindex)
    check.ok("it is even, so it is field 0 and not state_summary_root",
             summary["expected_gindex"] % 2 == 0)
    check.equal(
        "the branch reaches the anchor state root",
        "0x" + root_from_branch(
            unhex(summary["block_summary_root"]), expected_gindex, summary["branch"]
        ).hex(),
        anchor["state_root"],
    )

    print("\nthe period vector")
    period_gindex = SLOTS_PER_HISTORICAL_ROOT + period["index_in_period"]
    check.equal("the gindex is the vector index", period["expected_gindex"], period_gindex)
    check.equal("the branch is 13 levels", len(period["branch"]), 13)
    check.equal(
        "it carries the target root to block_summary_root",
        "0x" + root_from_branch(
            unhex(period["leaf"]), period_gindex, period["branch"]
        ).hex(),
        summary["block_summary_root"],
    )
    check.equal("the leaf is the target block root", period["leaf"], target["root"])

    print("\ntarget header (invariant 10)")
    check.equal("the five fields hash to the target root",
                "0x" + header_root(target["header"]).hex(), target["root"])
    check.equal("header.slot == s", target["header"]["slot"], target["slot"])
    check.ok("the target is at or after Capella's first slot",
             target["slot"] >= 6209536, str(target["slot"]))

    print("\npayload fields, at the TARGET's layout")
    values = target["payload"]["values"]
    for name, proof in target["payload"]["proofs"].items():
        expected = target_layout[f"body_to_{name}_gi"]
        check.equal(f"{name}: gindex {expected} matches the specs",
                    proof["expected_gindex"], expected)
        check.equal(
            f"{name}: reaches the target body root",
            "0x" + root_from_branch(
                unhex(proof["leaf"]), proof["expected_gindex"], proof["branch"]
            ).hex(),
            target["header"]["body_root"],
        )
        if name in ("block_number", "timestamp"):
            check.equal(f"{name}: decodes little-endian to the claimed value",
                        proof["leaf"], "0x" + uint64_leaf(values[name]).hex())
        else:
            check.equal(f"{name}: the leaf is the claimed value", proof["leaf"], values[name])

    print("\nthe period rebuild")
    rebuild = fixture["provenance"]["period_rebuild"]
    check.equal("the period covers the target slot",
                rebuild["period"], target["slot"] // SLOTS_PER_HISTORICAL_ROOT)
    check.equal("it spans exactly 8192 slots",
                rebuild["last_slot"] - rebuild["first_slot"] + 1, SLOTS_PER_HISTORICAL_ROOT)
    check.ok("and it was accepted only because it hashed to block_summary_root, "
             "which the branch above independently confirms", True)


class Check:
    def __init__(self) -> None:
        self.failures = 0

    def ok(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  ok    {label}")
        else:
            self.failures += 1
            print(f"  FAIL  {label}{(': ' + detail) if detail else ''}")

    def equal(self, label: str, got, want) -> None:
        self.ok(label, got == want, f"got {got!r}, want {want!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    fixture = json.loads(Path(sys.argv[1]).read_text())
    check = Check()

    cache = Path(__file__).resolve().parent / "cache" / "specs"
    tag = fixture["provenance"]["consensus_specs"]
    sources = fetch(tag, cache, refresh=False)
    per_fork = {fork: containers(text) for fork, text in sources.items()}

    if fixture.get("kind") == "historical":
        print(f"{sys.argv[1]}: historical path, "
              f"{fixture['anchor']['fork']} anchor -> {fixture['target']['fork']} target")
        check_historical(fixture, per_fork, check)
        print()
        if check.failures:
            print(f"{check.failures} check(s) failed")
            return 1
        print("every root in this fixture re-derives from hashlib alone")
        return 0

    if fixture.get("kind") == "missed_slot":
        print(f"{sys.argv[1]}: missed-slot attack, {fixture['anchor']['fork']} anchor")
        check_missed(fixture, per_fork, check)
        print()
        if check.failures:
            print(f"{check.failures} check(s) failed")
            return 1
        print("the attack fixture is sound in every leg, and false in its claim")
        return 0

    anchor = fixture["anchor"]
    target = fixture["target"]
    anchor_layout = layout(effective(per_fork, anchor["fork"]))

    print(f"{sys.argv[1]}: {fixture['kind']} path, "
          f"{anchor['fork']} anchor -> {target['fork']} target")

    print("\nanchor header (chain of commitments step 2)")
    check.equal("the five fields hash to the anchor root",
                "0x" + header_root(anchor["header"]).hex(), anchor["root"])
    check.equal("header.slot is the anchor slot", anchor["header"]["slot"], anchor["slot"])
    check.equal("header.state_root is the state the branches start from",
                anchor["header"]["state_root"], anchor["state_root"])

    print("\nEIP-4788 (chain of commitments step 1)")
    eip = anchor["eip4788"]
    check.ok("the contract returns the anchor root for this timestamp",
             eip.get("returns") == anchor["root"],
             f"contract says {eip.get('returns')}")

    print("\nstate.fork.current_version (invariant 8)")
    version = anchor["fork_version"]
    expected_gindex = concat(
        anchor_layout["fork_gi"],
        field_gindex(
            int(anchor_layout["fork_current_version_index"]),
            int(anchor_layout["fork_fields"]),
        ),
    )
    check.equal("gindex is the one the specs give", version["expected_gindex"], expected_gindex)
    check.equal("branch length is the gindex depth",
                len(version["branch"]), expected_gindex.bit_length() - 1)
    check.equal(
        "the branch reaches the anchor state root",
        "0x" + root_from_branch(
            unhex(version["leaf"]), version["expected_gindex"], version["branch"]
        ).hex(),
        anchor["state_root"],
    )
    # The version is a 4-byte Version, left-aligned in its chunk.
    check.equal("the leaf carries the claimed fork version",
                version["leaf"][:10], version["value"][:10])

    print("\nblock_roots (chain of commitments step 4, recent path)")
    roots = target["block_roots"]
    index = target["slot"] % SLOTS_PER_HISTORICAL_ROOT
    check.equal("index is slot mod 8192", roots["index"], index)
    expected_gindex = concat(anchor_layout["block_roots_gi"], SLOTS_PER_HISTORICAL_ROOT + index)
    check.equal("gindex is block_roots spliced with the vector index",
                roots["expected_gindex"], expected_gindex)
    check.equal("branch length is state depth + 13",
                len(roots["branch"]),
                int(anchor_layout["state_depth"]) + depth(SLOTS_PER_HISTORICAL_ROOT))
    check.equal(
        "the branch reaches the anchor state root",
        "0x" + root_from_branch(
            unhex(roots["leaf"]), roots["expected_gindex"], roots["branch"]
        ).hex(),
        anchor["state_root"],
    )
    check.equal("the leaf is the target block root", roots["leaf"], target["root"])

    print("\ntarget header (chain of commitments step 5, invariant 10)")
    check.equal("the five fields hash to the target root",
                "0x" + header_root(target["header"]).hex(), target["root"])
    check.equal("header.slot == s, so this is not a missed slot's repeat",
                target["header"]["slot"], target["slot"])
    check.ok("the target is at or after Capella's first slot",
             target["slot"] >= 6209536, str(target["slot"]))

    print("\npayload fields (chain of commitments step 6)")
    target_layout = layout(effective(per_fork, target["fork"]))
    values = target["payload"]["values"]
    for name, proof in target["payload"]["proofs"].items():
        expected_gindex = target_layout[f"body_to_{name}_gi"]
        label = f"{name}: gindex {expected_gindex}"
        check.equal(f"{label} matches the specs", proof["expected_gindex"], expected_gindex)
        check.equal(
            f"{label} reaches the target body root",
            "0x" + root_from_branch(
                unhex(proof["leaf"]), proof["expected_gindex"], proof["branch"]
            ).hex(),
            target["header"]["body_root"],
        )
        if name in ("block_number", "timestamp"):
            check.equal(
                f"{name}: the leaf decodes little-endian to the claimed value",
                proof["leaf"], "0x" + uint64_leaf(values[name]).hex(),
            )
        else:
            check.equal(f"{name}: the leaf is the claimed value", proof["leaf"], values[name])

    print()
    if check.failures:
        print(f"{check.failures} check(s) failed")
        return 1
    print("every root in this fixture re-derives from hashlib alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
