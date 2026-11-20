# Architecture

One source, two targets. Every line of proof logic lives in the `verife`
ingot. `contract` and `cli` supply two things each and nothing more: where the
anchor root comes from, and which SHA-256 to use.

```
verife/          core library (no storage, no I/O)
  gindex.fe      const fn gindex math: depth, field_gindex, concat, bounds
  layout.fe      one type per fork's SSZ layout            (not yet written)
  hash.fe        ChunkHasher: sha256(left || right), two impls
  merkle.fe      branch verification driven by a gindex
  header.fe      BeaconBlockHeader hashing, uint64 leaves
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

## The hasher

`ChunkHasher` has one method, `hash_pair(left, right) = sha256(left ‖ right)`,
and two implementations selected by `#[cfg(target = ...)]`:

| Impl | Backend | Route |
| --- | --- | --- |
| `PrecompileSha256` | EVM | `std::evm::ssz::hash_pair`, i.e. precompile `0x02` |
| `SoftSha256` | any | `core::hash::Sha256`, software |

`SoftSha256` compiles everywhere, so the core tests run it on both backends;
`both_hashers_agree` pins the two to identical trees on the EVM.

Fe's std turned out to carry a whole SSZ module — `hash_pair`, `u64_chunk`
(little-endian `uint64` packing), `mix_in_length` and `Merkleize` — present
since Fe 26.2.0. VeriFe calls it rather than reimplementing the staticcall.
It lives under `std::evm`, so it is unavailable natively; that is why the
hasher is a trait with a `#[cfg]`-selected implementation rather than a
direct call.

## The branch walk

`merkle::root_from_branch(hasher, leaf, gindex, branch)` returns the root that
`leaf` implies, and `verify_branch` compares it with one already trusted. The
branch is a `[u256; N]`, so a proof carries its length in its type.

Two invariants live only here:

- **Sides come from the gindex.** A node is a left child exactly when its
  gindex is even. There is no parameter for which side a sibling takes.
- **Length equals depth.** `N` is checked against the gindex's depth before
  any hashing, and the walk must land on node 1. Those two checks are
  equivalent -- `gindex >> N == 1` iff `N` is the depth -- and both are kept:
  one is an early exit, the other a backstop.

`std::evm::merkle::process_proof` is *not* used, despite looking like exactly
this function. It is the OpenZeppelin construction -- keccak256 over a
**sorted** pair -- and sorting is what makes an OZ proof position-independent.
An SSZ proof must commit to where a leaf sits, so a sorted-pair verifier would
accept a sibling moved to the other side: the Lido 2025 bug class in miniature.

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
