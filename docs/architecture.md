# Architecture

One source, two targets. Every line of proof logic lives in the `verife`
ingot. `contract` and `cli` supply two things each and nothing more: where the
anchor root comes from, and which SHA-256 to use.

```
verife/          core library (no storage, no I/O)
  gindex.fe      const fn gindex math: depth, field_gindex, concat, bounds
  layout.fe      one type per fork, and the proof shapes it implies
  hash.fe        ChunkHasher: sha256(left || right), two impls
  ssz.fe         uint64 chunk codec, List length mix-in
  merkle.fe      branches, vector and list elements, by gindex
  header.fe      BeaconBlockHeader hashing, uint64 leaves
  verify.fe      the recent, historical and cached paths
  anchor.fe      AnchorSource: an associated effect row, two impls
  prove.fe       the paths composed, generic over the anchor source
  cache.fe       the write-once rule for a stored period commitment
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
in the CLI it returns a root supplied directly. `fe test` cannot send a call
from the EIP-4788 system address and the test EVM has no beacon-roots contract,
so this is what makes the same code testable on both backends -- and what makes
the *deployed* path tested rather than merely compiled.

`verife/src/anchor.fe` does this with an **associated effect row**:

```fe
pub trait AnchorSource {
    uses E
    fn root_at(self, timestamp: u64) -> u256 uses E
}
```

Each implementation binds `E` to the effects its own `root_at` needs:

| Implementation | `E` | Available on |
| --- | --- | --- |
| `FixedAnchor { timestamp, root }` | nothing | every backend |
| `Eip4788 {}` | `(call: Call)` | the EVM target only |

A caller generic over the source forwards the row with `uses S::E`, which is
what `verife::prove`'s entry points do. Three consequences:

* The EVM `Call` effect never enters the native build. `Eip4788` is
  `#[cfg(target = "evm")]`, and nothing in the proof path mentions it.
* A function cannot read an anchor root without saying so in its signature.
  `compile_fail/undeclared_anchor_effect` is that mistake, and it does not
  compile: "fetch the anchor root" cannot be disguised as a getter.
* `contract/` and `cli/` contain no proof logic at all. Each binds two type
  parameters -- the anchor source and the hasher -- and calls the same
  `verife::prove` functions the tests call.

`FixedAnchor` carries the timestamp as well as the root, and reverts if asked
for any other one. Without that, a test or a CLI run could verify a proof built
against one anchor using a root from another, and the mismatch would surface as
an unrelated branch failure rather than as the error it is.

## The period cache, and surviving a fork

The historical path returns the `block_summary_root` it proved as well as the
field value, and the contract stores it. `proveCached*` then starts from a
stored root instead of an anchor.

The reason this is sound is that `historical_summaries` is append-only and the
periods in it are finalized: a `block_summary_root` commits to 8,192 finalized
block roots, so proving one is a permanent statement. The legs below it are
either fork-independent (the period vector is 13 levels in every layout) or
governed by the *target's* layout, and every target is in the past.

What follows is the part worth noticing. `prove_cached_payload_root` has no
`A: ForkLayout` and no `S: AnchorSource`, so it carries no effect row; the
contract's cached arms therefore do not declare `uses (call)`, and **the
compiler is what establishes that they make no EIP-4788 call** rather than a
comment claiming it. A cached period stays answerable through a fork nobody
has specified yet, with no redeployment.

The cost is that a stored root is a second thing a proof can start from, so
invariant 1 is restated: the anchor root is the only trusted *input*, and a
stored summary root is not an input but a value proved from one earlier,
admitted by a single write-once code path and never read from calldata.
`verife/src/cache.fe` holds that rule, and holds it in the library rather than
the contract precisely so it can be tested -- nothing in a `recv` arm is
reachable from `fe test`. Five tests cover it, including that a written period
can be neither rewritten nor cleared.

`docs/forward-compat.md` has the full argument, the limits of the cache, and
the specification of the self-validating fork registry that would also close
the live window.

## The layout table

The per-fork table of field counts, depths and gindices that this design rests
on is in `verife/src/layout.fe`, as one Fe type per fork with the derived values
pinned by `static_assert`. It was drafted from memory of the consensus specs and
is **not trusted on that basis**: `tools/layout_check.py` re-derives every value
from consensus-specs v1.6.1, and `--cross-check` diffs that against
`@lodestar/types`, which hand-writes the same containers in TypeScript. Both run
in CI, so a bug in the spec-markdown parser cannot hide behind a bug in the
table.
