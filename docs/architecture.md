# Architecture

One source, two targets. Every line of proof logic lives in the `verife`
ingot. `contract` and `cli` supply two things each and nothing more: where the
anchor root comes from, and which SHA-256 to use.

```
verife/          core library (no storage, no I/O)
  gindex.fe      const fn gindex math: depth, field_gindex, concat, bounds
  layout.fe      one type per fork's SSZ layout            (not yet written)
  hash.fe        the Hasher interface                      (not yet written)
  merkle.fe      branch verification driven by a gindex    (not yet written)
  header.fe      BeaconBlockHeader hashing and fields      (not yet written)
  verify.fe      the recent path and the historical path   (not yet written)
  dispatch.fe    Fork, boundaries, (anchor, target) match  (not yet written)
contract/        EVM verifier: anchor = EIP-4788 call, hasher = precompile 0x02
cli/             native CLI: verify, explain, calldata; software SHA-256
compile_fail/    ingots that must NOT compile, each with its diagnostic
fixtures/        mainnet proof fixtures (JSON) with provenance
tools/           proof generator, cross-check, compile-fail checker (not Fe)
bench/           Solidity baseline verifier and the gas harness
docs/            design notes, Fe findings, Gloas design
```

## The chain of commitments

1. **Anchor root.** Calling the EIP-4788 contract with an execution timestamp
   returns the *parent* beacon block root of that execution block. The buffer
   holds 8,191 entries, about 27 hours.
2. **Anchor header.** Hash the five `BeaconBlockHeader` fields and require the
   result to equal the anchor root. That yields the anchor slot and state root.
3. **Anchor state.** `block_roots` covers the last 8,192 slots;
   `historical_summaries` covers everything back to Capella.
4. **Target root.** Recent path: index `block_roots`. Historical path: prove
   `historical_summaries[i].block_summary_root` — field 0 only, at exact depth
   — then index that period's vector.
5. **Target header.** Hash its five fields, and require its slot to be the slot
   that was asked for.
6. **Payload field.** From `body_root` to `execution_payload`, then the field.

## Why the gindex math is `const fn`

Every position in that chain is derived from a layout type at compile time and
pinned with `static_assert`. Nothing is typed by hand and nothing is accepted
from a caller, so a proof built for the wrong fork's layout does not compile.
`docs/prior-art.md` records what this is a response to.

## Anchor source as an effect

The verifier reads its anchor root through an effect rather than calling
EIP-4788 directly. On chain the effect performs the system call; in tests and
in the CLI it returns a fixture root. `fe test` cannot send a call from the
EIP-4788 system address, so this is what makes the same code testable on both
backends.

## Open layout questions

The per-fork table of field counts, depths and gindices that this design
rests on was drafted from memory of the consensus specs. **It is not yet in
the code**, and none of it should be committed as a layout type until every
value has been confirmed against the specs and an independent SSZ library.
See `docs/open-questions.md`.
