#!/usr/bin/env python3
"""Encode a `proveRecentReceiptLog` call from the committed fixtures.

    python3 tools/event_calldata.py

The selector comes from `cast sig` over the same signature string
`verife/src/abi.fe` holds, so drift shows up as a reverted call rather than as
a call that quietly reaches a different function. Everything else comes out of
`fixtures/recent_join.json` and `fixtures/mpt/receipts_join.json`.
"""
import json, subprocess, sys
from pathlib import Path

H = "(uint64,uint64,uint256,uint256,uint256)"
SIG = ("proveRecentReceiptLog(uint64," + H + ",uint256[8],uint64," + H +
       ",uint256[19],uint256[9],uint256,bytes,bytes,uint256)")

root = Path(__file__).resolve().parent.parent
beacon = json.loads((root / "fixtures/recent_join.json").read_text())
ev = json.loads((root / "fixtures/mpt/receipts_join.json").read_text())

def word(v):
    if isinstance(v, str):
        v = int(v, 16) if v.startswith("0x") else int(v)
    return int(v).to_bytes(32, "big")

def rlp_len(n, short, long):
    if n <= 55: return bytes([short + n])
    be = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([long + len(be)]) + be

def rlp_str(b):
    return b if len(b) == 1 and b[0] < 0x80 else rlp_len(len(b), 0x80, 0xb7) + b

def rlp_list(items):
    body = b"".join(items)
    return rlp_len(len(body), 0xc0, 0xf7) + body

def header_words(h):
    return [word(h["slot"]), word(h["proposer_index"]), word(h["parent_root"]),
            word(h["state_root"]), word(h["body_root"])]

sel = subprocess.run(["cast", "sig", SIG], capture_output=True, text=True, check=True).stdout.strip()
a, t = beacon["anchor"], beacon["target"]
r = ev["receipt"]

head = [word(a["eip4788"]["timestamp"])]
head += header_words(a["header"])
head += [word(x) for x in a["fork_version"]["branch"]]
head.append(word(t["slot"]))
head += header_words(t["header"])
head += [word(x) for x in t["block_roots"]["branch"]]
head += [word(x) for x in t["payload"]["proofs"]["receipts_root"]["branch"]]
head.append(word(t["payload"]["values"]["receipts_root"]))

key_blob = bytes.fromhex(r["key"][2:])
proof_blob = rlp_list([rlp_str(bytes.fromhex(n[2:])) for n in r["proof"]])

head_words = len(head) + 3                      # two bytes offsets + log_index
off_key = head_words * 32
off_proof = off_key + 32 + (len(key_blob) + 31) // 32 * 32

def tail(b):
    return len(b).to_bytes(32, "big") + b + b"\x00" * ((-len(b)) % 32)

data = (bytes.fromhex(sel[2:]) + b"".join(head)
        + word(off_key) + word(off_proof) + word(0)     # log_index 0
        + tail(key_blob) + tail(proof_blob))

print("0x" + data.hex())
log0 = r["logs"][0]
print(f"selector      {sel}", file=sys.stderr)
print(f"calldata      {len(data)} bytes", file=sys.stderr)
print(f"block         {ev['provenance']['block_number']:,}  tx {r['tx_index']}  log 0", file=sys.stderr)
print(f"log address   {log0['address']}", file=sys.stderr)
print(f"log topic0    {log0['topics'][0]}", file=sys.stderr)
