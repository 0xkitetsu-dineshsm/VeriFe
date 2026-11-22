#!/usr/bin/env python3
"""Check every beacon fixture's proven payload values against the execution chain.

    python3 tools/payload_check.py fixtures/*.json

The payload values in a fixture are proven from a beacon block root: an SSZ
branch from `BeaconState` down to a field of `ExecutionPayload`. `fixture_check.py`
re-derives every one of those roots from `hashlib`, which establishes that the
branches are internally consistent -- but every number in that chain still comes
from one source, the beacon chain.

This asks a second, unrelated source. An execution RPC is told a block *number*
and reports that block's `stateRoot`, `receiptsRoot`, `hash` and `timestamp`;
those must equal what the SSZ proof established. The two sides share no code and
no data path: one walks a Merkle tree out of a consensus-layer state, the other
reads an execution-layer header.

It is the same discipline as `layout_check.py --cross-check`, which holds the
layout numbers to consensus-specs *and* `@lodestar/types`. A value agreed on by
two independent sources is a different kind of claim from one derived twice from
the same source.

Needs a network. `rpc.flashbots.net` answers `eth_getBlockByNumber` at any depth
keyless, which is what this uses; it refuses `eth_getProof` past ~128 blocks, but
that is not needed here.
"""
from __future__ import annotations
import json
import sys
import urllib.request
from pathlib import Path

RPC = "https://rpc.flashbots.net"
# Which payload field maps to which execution-header field. `block_number` and
# the block's own number are the same thing, checked separately.
HEADER_FIELD = {
    "state_root": "stateRoot",
    "receipts_root": "receiptsRoot",
    "block_hash": "hash",
    "timestamp": "timestamp",
}


def rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        out = json.load(response)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def check(path: Path) -> tuple[int, int]:
    fixture = json.loads(path.read_text())
    target = fixture.get("target") or {}
    values = (target.get("payload") or {}).get("values") or {}
    if not values:
        print(f"  skip  {path.name}: no proven payload values")
        return 0, 0
    number = values.get("block_number")
    if number is None:
        print(f"  skip  {path.name}: no proven block_number to look the block up by")
        return 0, 0

    header = rpc("eth_getBlockByNumber", [hex(int(number)), False])
    ok = bad = 0
    # The block the fixture proves must be the block the chain has at that number.
    if int(header["number"], 16) == int(number):
        print(f"  ok    {path.name}: block {int(number):,} is the block at that number")
        ok += 1
    else:
        print(f"  FAIL  {path.name}: asked for {number}, chain returned {header['number']}")
        bad += 1

    for field, header_key in HEADER_FIELD.items():
        if field not in values:
            continue
        proven = values[field]
        actual = header[header_key]
        same = (int(str(proven), 16) if str(proven).startswith("0x") else int(proven)) == int(actual, 16)
        if same:
            print(f"  ok    {path.name}: {field} agrees with the execution header")
            ok += 1
        else:
            print(f"  FAIL  {path.name}: {field} proven {proven}, header says {actual}")
            bad += 1
    return ok, bad


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        print("usage: payload_check.py fixtures/*.json", file=sys.stderr)
        return 2
    total_ok = total_bad = 0
    for path in paths:
        if not path.is_file():
            continue
        try:
            ok, bad = check(path)
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            print(f"  FAIL  {path.name}: {type(error).__name__}: {error}")
            total_bad += 1
            continue
        total_ok += ok
        total_bad += bad
    print()
    if total_bad:
        print(f"{total_bad} disagreement(s) with the execution chain, {total_ok} ok")
        return 1
    print(f"{total_ok} proven payload values agree with the execution chain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
