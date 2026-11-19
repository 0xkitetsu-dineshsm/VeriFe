# VeriFe

**Prove a field of any post-Capella block's execution payload — `block_hash`,
`state_root`, `receipts_root`, `block_number` — from a single EIP-4788 beacon
block root, with one Fe source that compiles to both an on-chain verifier and a
native CLI, where a proof built for the wrong fork's layout does not compile.**

> **Status: in progress.** This is the Fe Builders Challenge build window
> (November 3–24, 2026). The scaffolding, the compile-time gindex math and the
> first compile-fail case are in. The verifier itself is not. Every section
> below marks what is real; nothing here claims work that is not in the repo.

## For judges: one screen

| Claim | Command | Result today |
| --- | --- | --- |
| It builds on the pinned toolchain | `fe --version && fe check && fe build --backend native -i cli` | ✅ `fe 26.7.0 (e6e6342)` |
| One library, two backends | `fe test && fe test --backend native` | ✅ 12 on EVM, 10 native (2 are precompile-only) |
| Gindex math is derived, not typed by hand | `fe test -i verife` | ✅ `verife/src/gindex.fe` |
| SHA-256 matches the published SSZ zero hashes | `fe test -i verife -f zero_hash_chain` | ✅ `verife/src/hash.fe` |
| The precompile and the software hasher agree | `fe test -i verife -f both_hashers_agree` | ✅ the differential property in miniature |
| A layout mistake is a **build failure**, not a runtime check | `tools/compile_fail.sh` | ✅ 1 case; 3 more planned |
| A mainnet block's payload field verifies end to end | — | ⛔ not yet |
| Gas against a Solidity baseline | — | ⛔ not yet |

## The problem

EIP-4788 puts a beacon block root in the EVM, but only for about 27 hours —
8,191 slots. Reaching anything older means chaining SSZ Merkle proofs through
`BeaconState.historical_summaries`, and every step of that chain depends on
where a field sits in a container whose shape **changes at every hard fork**.

In Solidity those positions are hand-written constants, switched at run time:
Lido's CSVerifier pivots on a `PIVOT_SLOT` constructor argument, EigenLayer's
BeaconChainProofs on a `PECTRA_FORK_TIMESTAMP`. The constants are correct
because somebody checked them, and they stay correct because nobody edits them
wrong. In 2025 a high-severity bug was found in Lido's
`processHistoricalWithdrawalProof`: it took a **caller-supplied generalized
index** and checked only that it was somewhere under `historical_summaries` —
which lets a proof land on `state_summary_root` instead of
`block_summary_root`. See `docs/prior-art.md`.

## Approach

Make each fork's SSZ layout a Fe type, and derive every generalized index,
tree depth and proof length from that type with `const fn`, pinned by
`static_assert`. No gindex is typed by hand, and none is ever a parameter. The
only runtime indices are the summary index and the slot within a period, and
both are bounds-checked against depths the type fixes.

## Fe highlight

A bounds check written once, in a `const fn`, turns a wrong field position
into a compiler error — in a constant that never reaches run time:

```fe
pub const fn field_gindex(field: u64, field_count: u64) -> u64 {
    assert!(field < field_count, "field index past the end of the container")
    pow2(exp: depth(leaves: field_count)) + field
}
```

`compile_fail/field_past_end` asks for field 12 of Capella's 11-field
`BeaconBlockBody`. Fe refuses to build it:

```
error[3-0073]: assertion failed in const context
   ┌─ src/lib.fe:13:27
   │
13 │ const OUT_OF_RANGE: u64 = field_gindex(field: 12, field_count: CAPELLA_BODY_FIELDS)
   │                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ while evaluating this
   │
   = assertion message: field index past the end of the container
```

In Solidity that mistake is a wrong constant that compiles, deploys, and is
found by whoever verifies a proof against it.

## Architecture

`docs/architecture.md` has the full picture and the chain of commitments.

```
verife/        core library: all proof logic, no storage, no I/O
contract/      EVM verifier — anchor: EIP-4788 call, hasher: precompile 0x02
cli/           native CLI — anchor: fixture or RPC, hasher: software SHA-256
compile_fail/  ingots that must NOT compile, each with its diagnostic
fixtures/      mainnet proof fixtures with provenance
tools/         proof generator and checkers (not Fe; declared below)
bench/         Solidity baseline and the gas harness
docs/          architecture, prior art, Fe findings, open questions
```

One source, two targets: `contract` and `cli` each supply only an anchor
source. The hasher is already in the core library, picked by
`#[cfg(target = ...)]`: the SHA-256 precompile on the EVM, `core::hash`'s
software SHA-256 natively, with both proven to agree. The anchor source is an
effect, which is also what makes the verifier testable — `fe test` cannot send
a call from the EIP-4788 system address.

## Build and test

Fe **26.7.0** exactly, pinned in CI and here:

```sh
curl -fsSL https://raw.githubusercontent.com/argotorg/fe/master/feup/feup.sh \
  | bash -s -- --version v26.7.0
fe --version          # fe 26.7.0 (e6e6342)
```

| Layer | Command |
| --- | --- |
| Format | `fe fmt --check verife` (one ingot per call: `fe fmt` does not walk a workspace) |
| Types | `fe check` |
| Tests, EVM backend | `fe test` |
| Tests, native backend | `fe test --backend native` |
| Build the CLI | `fe build --backend native -i cli` |
| Must-not-compile suite | `tools/compile_fail.sh` |

No other tools are needed yet. The proof generator will need Python 3; it will
be declared here when it lands.

## Demo

Not yet. Planned: a reproducible CLI example proving a Capella block's
`block_hash` from a recent anchor, plus a short video.

## Limitations

- **The verifier is not written yet.** What exists is the workspace, the
  compile-time gindex math, the chunk hasher for both backends, and the first
  compile-fail case — all with tests.
- The per-fork layout table is **not in the code**, because it has not been
  verified against the consensus specs and an independent SSZ library.
- The anchor window is ~27 hours; older targets go through
  `historical_summaries`.
- Gloas / ePBS is designed for and documented, not implemented.
- Pre-Capella targets are out of scope, as are validator, balance and
  withdrawal proofs.
- Not audited. Nothing here is production code. Roots before finality can be
  reorged.

## Declaration

- **Pre-existing work:** none. The repository starts from the Fe Builders
  Challenge starter (commit `f9d9aa9`); its example vault contract and its
  `SUBMISSION.md` template were removed in the first VeriFe commit. Everything
  else was written inside the build window.
- **Third-party code:** none vendored. The design responds to Lido's CSVerifier
  and EigenLayer's BeaconChainProofs (see `docs/prior-art.md`); no code is
  copied from either.
- **AI assistance:** Claude (Claude Code) was used throughout — for the
  repository structure, drafting Fe and documentation, and checking Fe syntax
  against the compiler. Every compiler claim in this README was produced by
  running the command shown.

## License

Apache-2.0. See `LICENSE`.
