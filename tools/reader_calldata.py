#!/usr/bin/env python3
"""Encode a `proveHistoricalCapellaStorageSlot` call from the committed fixtures.

    python3 tools/reader_calldata.py > /tmp/calldata.hex

The selector is computed here from the same signature string `verife/src/abi.fe`
holds, so a drift between this and the contract shows up as a reverted call
rather than silently reaching another function. Everything else comes out of
the fixtures: nothing in this file is a proof value.
"""
import json
import subprocess
import sys
from pathlib import Path

H = "(uint64,uint64,uint256,uint256,uint256)"
SIG = ("proveHistoricalCapellaStorageSlot(uint64," + H + ",uint256[8],uint64," + H +
       ",uint64,uint64,uint256[32],uint256[7],uint256[13],uint256[8],uint256,"
       "uint256,uint256,bytes,bytes)")

root = Path(__file__).resolve().parent.parent
beacon = json.loads((root / "fixtures/historical_capella.json").read_text())
recent = json.loads((root / "fixtures/recent_fulu.json").read_text())
ex = json.loads((root / "fixtures/mpt/join_mainnet.json").read_text())   # placeholder, replaced below
ex = json.loads((root / "fixtures/mpt/hist_join_mainnet.json").read_text())

def word(v) -> bytes:
    if isinstance(v, str):
        v = int(v, 16) if v.startswith("0x") else int(v)
    return int(v).to_bytes(32, "big")

def rlp_len(n, short, long):
    if n <= 55:
        return bytes([short + n])
    be = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([long + len(be)]) + be

def rlp_str(b):
    return b if len(b) == 1 and b[0] < 0x80 else rlp_len(len(b), 0x80, 0xb7) + b

def rlp_list(items):
    body = b"".join(items)
    return rlp_len(len(body), 0xc0, 0xf7) + body

def proof_blob(nodes) -> bytes:
    """The RLP list of node encodings `mpt::lookup` walks."""
    return rlp_list([rlp_str(bytes.fromhex(n[2:])) for n in nodes])

def header_words(h) -> list:
    return [word(h["slot"]), word(h["proposer_index"]),
            word(h["parent_root"]), word(h["state_root"]), word(h["body_root"])]

selector = subprocess.run(["cast", "sig", SIG], capture_output=True, text=True, check=True).stdout.strip()

a, t = beacon["anchor"], beacon["target"]
pr = ex["cases"]["usdc"]["proof"]

head = []
head.append(word(a["eip4788"]["timestamp"]))
head += header_words(a["header"])
head += [word(x) for x in recent["anchor"]["fork_version"]["branch"]]
head.append(word(t["slot"]))
head += header_words(t["header"])
head.append(word(t["summary"]["index"]))
head.append(word(t["summary"]["length"]))
head += [word(x) for x in t["summary"]["branch"]]
head += [word(x) for x in t["summary"]["length_branch"]]
head += [word(x) for x in t["period"]["branch"]]
head += [word(x) for x in t["payload"]["proofs"]["state_root"]["branch"]]
head.append(word(t["payload"]["values"]["state_root"]))
head.append(word(ex["cases"]["usdc"]["address"]))
head.append(word(pr["storageProof"][0]["key"]))

account_blob = proof_blob(pr["accountProof"])
storage_blob = proof_blob(pr["storageProof"][0]["proof"])

# Two dynamic tails, so two offset words at the end of the head.
head_words = len(head) + 2
offset_account = head_words * 32
offset_storage = offset_account + 32 + (len(account_blob) + 31) // 32 * 32

def tail(b: bytes) -> bytes:
    pad = (-len(b)) % 32
    return len(b).to_bytes(32, "big") + b + b"\x00" * pad

data = (bytes.fromhex(selector[2:])
        + b"".join(head)
        + word(offset_account) + word(offset_storage)
        + tail(account_blob) + tail(storage_blob))

print("0x" + data.hex())
print(f"selector            {selector}", file=sys.stderr)
print(f"head words          {head_words}", file=sys.stderr)
print(f"account proof       {len(pr['accountProof'])} nodes, {len(account_blob)} bytes", file=sys.stderr)
print(f"storage proof       {len(pr['storageProof'][0]['proof'])} nodes, {len(storage_blob)} bytes", file=sys.stderr)
print(f"calldata            {len(data)} bytes", file=sys.stderr)
print(f"expect              {pr['storageProof'][0]['value']}", file=sys.stderr)
