#!/usr/bin/env python3
"""Generate Solidity interfaces to the Fe contracts, from their compiled ABIs.

    fe build -i contract -i reader --emit abi
    python3 tools/gen_solidity_iface.py

VeriFe is written in Fe; nearly every contract that would call it is written in
Solidity. Asking an integrator to read a Fe ingot and work out a calldata
layout is not reasonable, and a hand-written interface is a silent failure
waiting to happen -- one wrong argument type changes the selector, so the call
reaches no function, or a different one.

So the interface is generated from the ABI the compiler emitted, and
`tools/check_solidity_iface.py` then holds all three descriptions of each entry
point -- the signature `abi.fe` dispatches on, the compiled ABI, and this
interface -- to the same keccak256.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
HEADER_STRUCT = """/// @dev The five SSZ fields of a `BeaconBlockHeader`, in order.
///
/// NOT trusted for arriving: the verifier hashes it and requires the result to
/// equal a root it has already proven, so a wrong header reverts rather than
/// returning a wrong answer.
struct BeaconBlockHeader {
    uint64 slot;
    uint64 proposerIndex;
    uint256 parentRoot;
    uint256 stateRoot;
    uint256 bodyRoot;
}"""

def sol_type(i):
    return "BeaconBlockHeader" if i["type"] == "tuple" else i["type"]

def needs_location(t):
    return t == "bytes" or t == "BeaconBlockHeader" or "[" in t

def camel(name):
    return name

def render(contract, title, blurb):
    abi = json.loads((root / "out" / f"{contract}.abi.json").read_text())
    fns = []
    for e in sorted(abi, key=lambda x: x.get("name", "")):
        if e.get("type") != "function":
            continue
        args = []
        for i in e["inputs"]:
            t = sol_type(i)
            loc = " calldata" if needs_location(t) else ""
            args.append(f"{t}{loc} {camel(i['name'])}")
        rets = ", ".join(o["type"] for o in e["outputs"])
        # Every entry point is `external` and may write (the historical arms
        # fill the period cache), so none is marked `view`.
        body = ",\n        ".join(args) if args else ""
        sig = f"    function {e['name']}(\n        {body}\n    ) external returns ({rets});"
        fns.append(sig)
    iface = f"I{contract}" if contract != "Verife" else "IVerife"
    return f"""// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/// @title {iface} — {title}
/// @notice GENERATED from `out/{contract}.abi.json` by
/// `tools/gen_solidity_iface.py`. Do not edit by hand.
///
/// {blurb}
///
/// Every function is `external returns`, none is `view`: the historical arms
/// write the period cache as a side effect of an honest proof, so they cannot
/// be `staticcall`ed. Use the `proveCached*` arms for a read-only query once a
/// period has been proven once.
{HEADER_STRUCT}

interface {iface} {{
""" + "\n\n".join(fns) + "\n}\n"

Path(root / "integration").mkdir(exist_ok=True)
for contract, title, blurb in (
    ("Verife", "the consensus half: an EIP-4788 root to an execution payload field",
     "Establishes roots from the one trusted input -- whatever the beacon-roots\n/// contract returns for a timestamp."),
    ("Reader", "the execution half: a state root to a storage slot",
     "Reads into a root. `read*` takes a state root as an ARGUMENT and verifies\n/// only the trie walk; `prove*` proves the root it walks out of a beacon root."),
):
    out = root / "integration" / f"I{contract}.sol"
    out.write_text(render(contract, title, blurb))
    n = render(contract, title, blurb).count("function ")
    print(f"wrote {out.relative_to(root)}: {n} functions")
