# Prior art

VeriFe is not the first on-chain verifier of historical beacon data, and does
not claim to be. It is an argument that the type system should be doing work
that these codebases do at run time.

## Lido CSVerifier

Verifies withdrawal and slashing proofs against EIP-4788 roots. It pivots
between fork layouts at run time with a `PIVOT_SLOT` constructor argument, and
LIP-27 covers the Electra layout change. In 2025 a high-severity bug was found
in `processHistoricalWithdrawalProof`: it accepted a **caller-supplied gindex**
and checked only that it was a child of `historical_summaries`, which admits a
proof landing on `state_summary_root` instead of `block_summary_root`.

That is the bug class VeriFe is built around: no gindex is ever an input, and
the historical path lands on field 0 at an exact depth or not at all.

## EigenLayer BeaconChainProofs

Verifies validator and balance proofs. Switches layout on
`PECTRA_FORK_TIMESTAMP`, and documents the EIP-4788 parent-root subtlety
carefully. Validator and balance proofs are explicitly out of VeriFe's scope.

## fevm-replay

Complementary rather than overlapping: it ports the contracts that *store*
roots. VeriFe proves what those roots commit to.

## eth-historian

A Rust tool for historical beacon proofs, off-chain only.

## What is new here

Not the proof chain, which is well understood. What is new is that each fork's
SSZ layout is a Fe type, every gindex and depth is derived from that type by
`const fn` and pinned with `static_assert`, and the mistakes the codebases
above guard against at run time become build failures. `compile_fail/` is the
evidence.
