#!/usr/bin/env bash
# Everything this project claims, checked in one command.
#
#   ./check.sh           run every check
#   ./check.sh --fast    skip the native backend and the Python/Node checks
#
# Exits non-zero if anything fails. Each step's output is kept and printed on
# failure, so a red line is always followed by the reason for it.
#
# A step that needs something this machine does not have -- Node modules for
# the independent layout cross-check, a spec cache and no network -- is
# reported as `skip` with the reason, not as a pass. CI installs everything, so
# nothing is skipped there.

set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

PINNED_FE="26.7.0"
EIP170_LIMIT=24576
INGOTS="verife contract cli reader"
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
fi

logs="$(mktemp -d)"
trap 'rm -rf "$logs"' EXIT
ok_count=0
fail_count=0
skip_count=0
failed_names=""

# Colour only on a terminal, so a CI log or a pipe stays plain text and the
# `ok`/`FAIL`/`skip` columns can be grepped.
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    green() { printf '\033[32m%s\033[0m' "$1"; }
    red() { printf '\033[31m%s\033[0m' "$1"; }
    grey() { printf '\033[90m%s\033[0m' "$1"; }
else
    green() { printf '%s' "$1"; }
    red() { printf '%s' "$1"; }
    grey() { printf '%s' "$1"; }
fi

ok() { # ok <name> [detail]
    ok_count=$((ok_count + 1))
    printf '  %s  %-46s %s\n' "$(green ok)" "$1" "$(grey "${2:-}")"
}

bad() { # bad <name> <logfile>
    fail_count=$((fail_count + 1))
    failed_names="$failed_names
    $1"
    printf '  %s %-46s %s\n' "$(red FAIL)" "$1" "$(grey "${2:-}")"
    if [[ -s "${2:-}" ]]; then
        sed 's/^/        /' "$2" | tail -25
    fi
}

skip() { # skip <name> <reason>
    skip_count=$((skip_count + 1))
    printf '  %s %-46s %s\n' "$(grey skip)" "$1" "$(grey "$2")"
}

logfile() { echo "$logs/$(echo "$1" | tr -c 'a-zA-Z0-9' '_').log"; }

step() { # step <name> <command...>
    local name="$1"
    shift
    local log
    log="$(logfile "$name")"
    if "$@" >"$log" 2>&1; then
        ok "$name"
    else
        bad "$name" "$log"
    fi
}

echo
echo "VeriFe — $(date -u '+%Y-%m-%d %H:%M UTC')"
echo

# --- The toolchain ----------------------------------------------------------

version="$(fe --version 2>/dev/null)"
if [[ "$version" == *"$PINNED_FE"* ]]; then
    ok "Fe is the pinned $PINNED_FE" "$version"
else
    log="$(logfile version)"
    echo "expected Fe $PINNED_FE, found: ${version:-nothing on PATH}" >"$log"
    echo "install: curl -fsSL https://raw.githubusercontent.com/argotorg/fe/master/feup/feup.sh | bash -s -- --version v$PINNED_FE" >>"$log"
    bad "Fe is the pinned $PINNED_FE" "$log"
fi

# --- The Fe source ----------------------------------------------------------

# `fe fmt` does not walk a workspace (docs/upstream/02), so each ingot is
# checked on its own. A bare `fe fmt --check` at the root passes trivially.
fmt_log="$(logfile fmt)"
: >"$fmt_log"
fmt_ok=1
for ingot in $INGOTS; do
    fe fmt --check "$ingot" >>"$fmt_log" 2>&1 || fmt_ok=0
done
if ((fmt_ok)); then
    ok "fe fmt --check" "$INGOTS"
else
    bad "fe fmt --check" "$fmt_log"
fi

step "fe check (the whole workspace)" fe check

# The two test runs must differ: the EVM run compiles the
# `#[cfg(target = "evm")]` code (the SHA-256 precompile and the std::evm::ssz
# agreement tests), the native run compiles it out.
evm_log="$(logfile "fe test evm")"
if fe test >"$evm_log" 2>&1; then
    ok "fe test (EVM backend)" "$(grep -oE '[0-9]+ passed' "$evm_log" | tail -1)"
else
    bad "fe test (EVM backend)" "$evm_log"
fi

if ((FAST)); then
    skip "fe test (native backend)" "--fast"
else
    native_log="$(logfile "fe test native")"
    if fe test --backend native >"$native_log" 2>&1; then
        ok "fe test (native backend)" "$(grep -oE '[0-9]+ passed' "$native_log" | tail -1)"
    else
        bad "fe test (native backend)" "$native_log"
    fi
fi

step "the CLI builds natively" fe build --backend native -i cli

# --- What must not compile --------------------------------------------------

cf_log="$(logfile compile_fail)"
if tools/compile_fail.sh >"$cf_log" 2>&1; then
    ok "compile-fail suite" "$(grep -c '^ok' "$cf_log") cases still refuse to compile"
else
    bad "compile-fail suite" "$cf_log"
fi

# --- EIP-170 ----------------------------------------------------------------
#
# `fe build` does not warn when runtime code passes the 24,576-byte limit (it
# was issue #1951, fixed by #1956 -- re-test before relying on it), so the
# limit is enforced here. The artifact is hex text, so a byte is two
# characters.

size_log="$(logfile eip170)"
# Clear any artifact from an earlier run first, so a stale one cannot be
# measured in place of what this build produced.
rm -f out/*.runtime.bin 2>/dev/null
if fe build -i contract --emit runtime-bytecode >"$size_log" 2>&1 \
    && fe build -i reader --emit runtime-bytecode >>"$size_log" 2>&1; then
    biggest=0
    biggest_name=""
    while IFS= read -r artifact; do
        # The artifact is hex text, so one byte of code is two characters.
        chars="$(tr -cd '0-9a-fA-F' <"$artifact" | wc -c)"
        bytes=$((chars / 2))
        if ((bytes > biggest)); then
            biggest=$bytes
            biggest_name="$(basename "$artifact" .runtime.bin)"
        fi
    done < <(find out -name '*.runtime.bin' 2>/dev/null)
    if ((biggest == 0)); then
        skip "contract runtime under $EIP170_LIMIT bytes" "no contract in contract/ yet"
    elif ((biggest < EIP170_LIMIT)); then
        # Every contract, not just the biggest: `reader` being comfortable
        # says nothing about `contract` being at 85% of the limit.
        all_sizes=""
        while IFS= read -r artifact; do
            b=$(( $(tr -cd '0-9a-fA-F' <"$artifact" | wc -c) / 2 ))
            all_sizes="$all_sizes$(basename "$artifact" .runtime.bin) $b, "
        done < <(find out -name '*.runtime.bin' 2>/dev/null | sort)
        ok "contracts under $EIP170_LIMIT bytes" "${all_sizes%, }"
    else
        echo "$biggest_name runtime is $biggest bytes, over the $EIP170_LIMIT limit" >"$size_log"
        bad "contract runtime under $EIP170_LIMIT bytes" "$size_log"
    fi
elif grep -q "No contracts found" "$size_log"; then
    skip "contract runtime under $EIP170_LIMIT bytes" "no contract in contract/ yet"
else
    bad "contract runtime under $EIP170_LIMIT bytes" "$size_log"
fi

# --- The proven values, against the execution chain -------------------------
#
# `fixture_check.py` re-derives every root in a fixture from hashlib, which
# establishes that its branches are internally consistent. But every number in
# that chain still comes from one source: the beacon chain. This asks an
# unrelated one -- an execution RPC is given a block *number* and reports that
# block's stateRoot, receiptsRoot, hash and timestamp, which must equal what
# the SSZ proof established. Same discipline as the lodestar cross-check on the
# layout numbers.

if ((FAST)); then
    skip "proven values vs the execution chain" "--fast"
else
    payload_log="$(logfile payload)"
    if python3 tools/payload_check.py fixtures/*.json >"$payload_log" 2>&1; then
        ok "proven values vs the execution chain" \
           "$(grep -c '^  ok  ' "$payload_log") values, 3 forks of history"
    else
        bad "proven values vs the execution chain" "$payload_log"
    fi
fi

# --- The MPT fixture, against the file it came from --------------------------
#
# `fixtures/*.json` are beacon fixtures and `fixture_check.py` re-derives every
# root in them from hashlib. The execution-layer fixture lives in
# `fixtures/mpt/` instead, because it is a different schema and its hashes are
# Keccak, which hashlib does not have. What is checked here is that the Fe
# module still matches the JSON it was generated from: a fixture edited by hand
# on one side only is the way a test starts passing against the wrong data.

if ((FAST)); then
    skip "the MPT fixture matches its source" "--fast"
elif [[ ! -f fixtures/mpt/mpt_mainnet.json ]]; then
    skip "the MPT fixture matches its source" "no execution-layer fixture"
elif ! command -v cast >/dev/null 2>&1; then
    skip "the MPT fixture matches its source" "needs cast for keccak"
else
    mpt_log="$(logfile mpt)"
    # One module per source file, named after it, so the set to compare is
    # derived from `fixtures/mpt/` rather than listed here and left to rot.
    before="$(mktemp -d)"
    for src in fixtures/mpt/*.json; do
        gen="verife/src/fixture_$(basename "$src" .json).fe"
        [[ -f "$gen" ]] && cp "$gen" "$before/$(basename "$gen")"
    done
    # The committed modules are formatted and the generator does not format, so
    # the regenerated copies go through `fe fmt` before comparing.
    regen_ok=1
    # Each generator skips a schema it does not own, so both are run over
    # every file and between them they cover the lot.
    for src in fixtures/mpt/*.json; do
        python3 tools/mpt_to_fe.py "$src" >>"$mpt_log" 2>&1 || regen_ok=0
        python3 tools/vectors_to_fe.py "$src" >>"$mpt_log" 2>&1 || regen_ok=0
    done
    fe fmt verife >>"$mpt_log" 2>&1 || regen_ok=0
    for gen in "$before"/*; do
        diff -q "$gen" "verife/src/$(basename "$gen")" >/dev/null 2>&1 || regen_ok=0
    done
    if ((regen_ok)); then
        ok "the MPT fixtures match their sources" \
           "$(ls "$before" | wc -l | tr -d ' ') modules, byte for byte"
    else
        for gen in "$before"/*; do
            diff "$gen" "verife/src/$(basename "$gen")" >>"$mpt_log" 2>&1
            cp "$gen" "verife/src/$(basename "$gen")"
        done
        bad "the MPT fixtures match their sources" "$mpt_log"
    fi
    rm -rf "$before"
fi

# --- The whole chain, in one transaction, on a fork of mainnet --------------
#
# Everything else here checks a leg. This checks the composition: one call to
# `reader` that starts at the real EIP-4788 contract and ends at a USDC
# storage slot as it stood in April 2023, plus six single-bit corruptions that
# must each be refused.
#
# Needs an archive endpoint, because forking at a two-day-old block does.
# Never reads a key from a file in this repo -- `ETH_ARCHIVE_RPC` or nothing.

if ((FAST)); then
    skip "the whole chain in one transaction" "--fast"
elif [[ -z "${ETH_ARCHIVE_RPC:-}" ]]; then
    skip "the whole chain in one transaction" "no ETH_ARCHIVE_RPC (archive access needed to fork)"
elif ! command -v anvil >/dev/null; then
    skip "the whole chain in one transaction" "anvil not installed"
else
    demo_log="$(logfile demo)"
    if tools/reader_demo.sh --port 8549 >"$demo_log" 2>&1; then
        ok "the whole chain in one transaction" \
           "$(grep -cE '^      the .* ok    refused' "$demo_log") controls refused, $(grep -oE '[0-9,]+ gas' "$demo_log" | head -1)"
    else
        bad "the whole chain in one transaction" "$demo_log"
    fi
fi

# --- The one leg fe test cannot reach ---------------------------------------
#
# `anchor::Eip4788` is the anchor source the deployed contract uses, and no
# unit test can run it: the test EVM has no beacon-roots contract and cannot
# call from the system address. tools/fork_check.sh deploys onto a fork of
# mainnet, where the real ring buffer is in ordinary contract storage, and
# checks `anchorRootAt` against each block's own parentBeaconBlockRoot.

if ((FAST)); then
    skip "the anchor source vs the real EIP-4788" "--fast"
else
    fork_log="$(logfile fork)"
    if tools/fork_check.sh >"$fork_log" 2>&1; then
        if grep -q '^skip:' "$fork_log"; then
            skip "the anchor source vs the real EIP-4788" "$(grep -m1 '^skip:' "$fork_log" | sed 's/^skip: //')"
        else
            ok "the anchor source vs the real EIP-4788" \
               "$(grep -c '^  ok  ' "$fork_log") mainnet blocks on a fork"
        fi
    else
        bad "the anchor source vs the real EIP-4788" "$fork_log"
    fi
fi

# --- The numbers, checked against sources outside this repository -----------

if ((FAST)); then
    skip "layout numbers vs consensus-specs" "--fast"
    skip "fixtures re-derived from hashlib" "--fast"
else
    have_specs=0
    [[ -d tools/cache/specs ]] && have_specs=1
    reachable=0
    if ((have_specs)); then
        reachable=1
    elif curl -fsS --max-time 8 -o /dev/null https://raw.githubusercontent.com 2>/dev/null; then
        reachable=1
    fi

    if ((!reachable)); then
        skip "layout numbers vs consensus-specs" "needs the spec cache or a network"
        skip "fixtures re-derived from hashlib" "needs the spec cache or a network"
    else
        cross=""
        if [[ -d tools/node_modules/@lodestar ]] && command -v node >/dev/null 2>&1; then
            cross="--cross-check"
        fi
        layout_log="$(logfile layout)"
        if python3 tools/layout_check.py $cross >"$layout_log" 2>&1; then
            if [[ -n "$cross" ]]; then
                ok "layout numbers vs consensus-specs" "and vs @lodestar/types"
            else
                ok "layout numbers vs consensus-specs" "(cd tools && npm ci) adds the lodestar cross-check"
            fi
        else
            bad "layout numbers vs consensus-specs" "$layout_log"
        fi

        fix_log="$(logfile fixtures)"
        : >"$fix_log"
        fixtures_ok=1
        count=0
        for fixture in fixtures/*.json; do
            [[ -e "$fixture" ]] || continue
            count=$((count + 1))
            python3 tools/fixture_check.py "$fixture" >>"$fix_log" 2>&1 || fixtures_ok=0
        done
        if ((count == 0)); then
            skip "fixtures re-derived from hashlib" "no fixtures"
        elif ((fixtures_ok)); then
            ok "fixtures re-derived from hashlib" "$count fixtures, every root"
        else
            bad "fixtures re-derived from hashlib" "$fix_log"
        fi
    fi
fi

# --- Summary ----------------------------------------------------------------

echo
if ((fail_count)); then
    printf '%s  %d ok, %d skipped\n' "$(red "$fail_count failed:")" "$ok_count" "$skip_count"
    printf '%s\n' "$failed_names" | sed '/^$/d'
    exit 1
fi
printf '%s  %d ok, %d skipped\n' "$(green 'all good.')" "$ok_count" "$skip_count"
