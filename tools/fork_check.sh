#!/usr/bin/env bash
# Deploy the verifier onto a fork of mainnet and check it against the real
# EIP-4788 contract.
#
#   tools/fork_check.sh [--block N] [--rpc URL]
#
# Why this exists
# ---------------
# `fe test` cannot reach one leg of the chain of commitments. The test EVM has
# no beacon-roots contract at 0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02 and
# cannot send a call from the EIP-4788 system address, so `anchor::Eip4788` --
# the anchor source the deployed contract actually uses -- is the only part of
# this project that unit tests compile but never run. `verife::prove` is
# generic over the anchor source precisely so that everything *above* that leg
# is tested with `FixedAnchor`; this script is what tests the leg itself.
#
# A fork of mainnet is better than a testnet for the job. The beacon-roots
# contract keeps its roots in ordinary contract storage, so a fork inherits the
# real ring buffer: the roots here are mainnet's, not a devnet's. And pinning
# `--block` makes the result reproducible for ever, where a testnet's state
# moves under you.
#
# What it proves: for each of the last few real mainnet blocks, the verifier's
# `anchorRootAt(block.timestamp)` returns that block's own
# `parentBeaconBlockRoot` as the header records it. That is EIP-4788's
# contract, checked against the chain rather than against our reading of it.
#
# What it does NOT prove: the SSZ proof paths. Those need a fixture whose
# anchor is still inside the 8,191-slot (~27.3 h) window at the fork block --
# see docs/forward-compat.md and the fixtures README.

set -uo pipefail
export FOUNDRY_DISABLE_NIGHTLY_WARNING=1

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

RPC="${FORK_RPC:-https://ethereum-rpc.publicnode.com}"
BLOCK=""
PORT="${FORK_PORT:-8545}"
# Anvil's first account, published in its own docs. Not a secret, and it only
# exists inside this throwaway fork.
KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
BEACON_ROOTS=0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02

while [[ $# -gt 0 ]]; do
    case "$1" in
        --block) BLOCK="$2"; shift 2 ;;
        --rpc) RPC="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        -h|--help) sed -n '2,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

for tool in anvil cast fe; do
    command -v "$tool" >/dev/null 2>&1 || { echo "skip: $tool is not on PATH"; exit 0; }
done

R="http://127.0.0.1:$PORT"
log="$(mktemp)"
anvil_pid=""
cleanup() {
    [[ -n "$anvil_pid" ]] && kill "$anvil_pid" 2>/dev/null
    rm -f "$log"
}
trap cleanup EXIT

echo "building the contract"
fe build -i contract --emit bytecode >/dev/null 2>&1 || {
    echo "FAIL: fe build -i contract"; exit 1; }
[[ -s out/Verife.bin ]] || { echo "FAIL: no out/Verife.bin"; exit 1; }

fork_args=(--fork-url "$RPC" --silent --port "$PORT")
[[ -n "$BLOCK" ]] && fork_args+=(--fork-block-number "$BLOCK")
echo "forking mainnet${BLOCK:+ at block $BLOCK}"
anvil "${fork_args[@]}" >"$log" 2>&1 &
anvil_pid=$!

# Wait for the node, without a busy loop.
ready=0
for _ in $(seq 1 40); do
    if cast block-number --rpc-url "$R" >/dev/null 2>&1; then ready=1; break; fi
    sleep 0.5
done
((ready)) || { echo "FAIL: anvil did not come up"; sed 's/^/    /' "$log" | tail -10; exit 1; }

fork_block="$(cast block-number --rpc-url "$R")"
chain="$(cast chain-id --rpc-url "$R")"
if [[ "$chain" != "1" ]]; then
    echo "FAIL: chain id is $chain, expected 1 (mainnet)"; exit 1
fi
code="$(cast code "$BEACON_ROOTS" --rpc-url "$R")"
if [[ ${#code} -lt 10 ]]; then
    echo "FAIL: no EIP-4788 contract at $BEACON_ROOTS on this fork"; exit 1
fi
echo "  fork block $fork_block, chain id $chain, beacon-roots contract present"

verifier="$(cast send --private-key "$KEY" --rpc-url "$R" --json --create "0x$(cat out/Verife.bin)" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["contractAddress"])')" || {
    echo "FAIL: deployment"; exit 1; }
echo "  deployed at $verifier"
echo

# `fork_block` is the last block that came from mainnet. Anything after it was
# mined by anvil, has a zero parentBeaconBlockRoot and never wrote to
# EIP-4788 -- so the real blocks are at and below the fork block.
failures=0
checked=0
for offset in 0 1 2 5 11; do
    b=$((fork_block - offset))
    j="$(cast block "$b" --rpc-url "$R" --json 2>/dev/null)" || continue
    read -r ts want <<<"$(printf '%s' "$j" | python3 -c '
import json,sys
d = json.load(sys.stdin)
root = d.get("parentBeaconBlockRoot")
print(int(d["timestamp"], 16), root if root else "none")')"
    [[ "$want" == "none" || "$want" == "0x0000000000000000000000000000000000000000000000000000000000000000" ]] && continue
    got="$(cast call "$verifier" "anchorRootAt(uint64)(uint256)" "$ts" --rpc-url "$R" 2>&1 | head -1 | awk '{print $1}')"
    checked=$((checked + 1))
    if python3 -c "
import sys
try: sys.exit(0 if int('$got') == int('$want', 16) else 1)
except Exception: sys.exit(1)"; then
        printf '  ok    block %s  ts %s  root %s…\n' "$b" "$ts" "${want:0:18}"
    else
        failures=$((failures + 1))
        printf '  FAIL  block %s  ts %s\n          header   %s\n          verifier %s\n' \
            "$b" "$ts" "$want" "$got"
    fi
done

echo
if ((checked == 0)); then
    echo "skip: no forked block carried a parentBeaconBlockRoot"
    exit 0
fi
if ((failures)); then
    echo "$failures of $checked blocks disagreed with the chain"
    exit 1
fi
echo "all good. $checked mainnet blocks: anchorRootAt matches parentBeaconBlockRoot"
echo "(the Eip4788 anchor source, checked against the real contract and not a mock)"
