#!/usr/bin/env python3
"""Every entry point's selector, three ways, and they must agree.

    python3 tools/check_solidity_iface.py

A hand-written Solidity interface to a Fe contract is a silent-failure waiting
to happen: get one argument type wrong and the selector changes, so calls go
to no function at all -- or, worse, to a different one. So the interface is
generated from the compiled ABI, and this checks the three descriptions of the
same thing against each other:

  1. `verife/src/abi.fe`   the signature string the Fe contract dispatches on
  2. `out/*.abi.json`      what the compiler actually emitted
  3. `integration/*.sol`   the interface a Solidity consumer would import

keccak256 of each is computed with `cast`, not by this script, so a bug here
cannot make the three agree.
"""
import json, re, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent

def sel(sig: str) -> str:
    return subprocess.run(["cast", "sig", sig], capture_output=True, text=True,
                          check=True).stdout.strip()

def canon(e) -> str:
    def t(i):
        if i["type"] == "tuple":
            return "(" + ",".join(c["type"] for c in i["components"]) + ")"
        return i["type"]
    return f"{e['name']}({','.join(t(i) for i in e['inputs'])})"

# 1. the signature strings abi.fe dispatches on (the const decl wraps, the
#    string itself does not)
# A short signature stays on the `sol(...)` line; a long one is wrapped onto
# its own. Match the string wherever it sits.
fe_sigs = set(re.findall(r'"([A-Za-z]\w*\([^"]*\))"',
                         (root / "verife/src/abi.fe").read_text()))

# 2. what each contract's ABI says
abi_sigs = {}
for name in ("Verife", "Reader"):
    p = root / "out" / f"{name}.abi.json"
    if not p.exists():
        print(f"skip: {p.name} not built -- run `fe build -i contract -i reader --emit abi`")
        sys.exit(0)
    for e in json.loads(p.read_text()):
        if e.get("type") == "function":
            abi_sigs[canon(e)] = name

# 3. what the generated Solidity declares
sol_fns = set()
for p in (root / "integration").glob("I*.sol"):
    text = p.read_text()
    for m in re.finditer(r"function\s+(\w+)\s*\(([^;]*?)\)\s*external", text, re.S):
        args = [a.strip() for a in m.group(2).split(",") if a.strip()]
        types = []
        for a in args:
            ty = a.split()[0]
            ty = "(uint64,uint64,uint256,uint256,uint256)" if ty == "BeaconBlockHeader" else ty
            types.append(ty)
        sol_fns.add(f"{m.group(1)}({','.join(types)})")

ok = bad = 0
for sig, contract in sorted(abi_sigs.items()):
    s = sel(sig)
    in_fe = sig in fe_sigs
    in_sol = sig in sol_fns
    if in_fe and in_sol:
        print(f"  ok   {s}  {contract}.{sig.split('(')[0]}")
        ok += 1
    else:
        missing = []
        if not in_fe:  missing.append("abi.fe")
        if not in_sol: missing.append("the Solidity interface")
        print(f"  FAIL {s}  {contract}.{sig.split('(')[0]} -- absent from {' and '.join(missing)}")
        bad += 1

print()
print(f"  {ok} entry points agree across abi.fe, the compiled ABI and the Solidity interface")
if bad:
    print(f"  {bad} DO NOT")
sys.exit(1 if bad else 0)
