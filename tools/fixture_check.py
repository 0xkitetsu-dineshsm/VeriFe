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
