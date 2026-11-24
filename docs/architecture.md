# Architecture

**One source, three targets.** Every line of proof logic lives in the `verife`
ingot. `contract`, `reader` and `cli` supply two things each and nothing more:
where the anchor root comes from, and which hash function to use.

```
verife/            core library (no storage, no I/O)
  --- the consensus layer: SSZ, SHA-256, positions from a type ---
  gindex.fe        const fn gindex math: depth, field_gindex, concat, bounds
  layout.fe        one type per fork, and the proof shapes it implies
  hash.fe          ChunkHasher (SHA-256) and ByteHasher (Keccak), two impls each
  ssz.fe           uint64 chunk codec, List length mix-in
  merkle.fe        branches, vector and list elements, by gindex
  header.fe        BeaconBlockHeader hashing, uint64 leaves
  verify.fe        the recent, historical and cached paths
  anchor.fe        AnchorSource: an associated effect row, two impls
  prove.fe         the paths composed, generic over the anchor source
  cache.fe         the write-once rule for a stored period commitment
  dispatch.fe      Fork, the boundary table, AnchorFor<T>, invariant 7
  abi.fe           one selector per entry point, and the calldata encoder
  --- the execution layer: RLP, Keccak-256, a hex-nibble trie ---
  rlp.fe           canonical RLP, read in place
  mpt.fe           Merkle-Patricia lookup: present, absent, or refused
  --- and the seam ---
  join.fe          one beacon root to a storage slot, in a single chain
contract/          EVM: establishes roots. Anchor = EIP-4788, hasher = precompile 0x02
reader/            EVM: reads into a root. 7 arms: storage at Capella/Deneb/
                   Electra, a receipt log, and two root-as-argument readers
cli/               native: verify, explain, calldata; software SHA-256 and Keccak
evm_mpt_tests/     real mainnet trie proofs, run on the EVM target
compile_fail/      7 ingots that must NOT compile, each with its diagnostic
integration/       IVerife.sol, IReader.sol, ExampleConsumer.sol (generated)
fixtures/          mainnet proof fixtures (JSON) with provenance
tools/             generators, independent checkers, prove.sh, fresh_clone.sh
bench/             intended Solidity baseline and gas harness (README only)
docs/              design notes, prior art, forward compatibility, Fe findings
```

## Why there are two contracts

`contract` is 20,771 bytes of the 24,576 EIP-170 allows, and the
Merkle-Patricia machinery does not fit beside it. So the execution-layer half
is a second contract, `reader`, at 16,900 bytes.

That was forced, but it is better than one contract would have been: it puts
the line between **proven** and **assumed** on a contract boundary instead of
in a comment. `reader`'s `readStorageSlot` takes a state root as an *argument*
and verifies only the trie walk — the name says `read`, not `prove`, so a
careless integrator has to type the word. `proveHistoricalCapellaStorageSlot`
proves the root it walks, and walks the value it proved rather than the one in
calldata.

`reader` is smaller than `contract` despite containing more machinery — the
whole historical SSZ path *plus* MPT *plus* RLP — because `contract`
monomorphises fifteen entry points and `reader` has seven. That is the honest
cost model of the typed-entry-point design: **size scales with entry points,
not with logic.**

Its seven arms split three ways. `readStorageSlot` and `readAccount` take a
state root **as an argument** and verify only the trie walk — useful to any
contract that already holds a trustworthy root, and named `read` rather than
`prove` so a careless integrator has to type the word.
`proveHistorical{Capella,Deneb,Electra}StorageSlot` prove the root they walk,
and differ from one another only where the consensus spec differs: Capella's
payload branch is `uint256[8]`, Deneb's and Electra's `uint256[9]`, because 15
fields against 17. `proveRecentReceiptLog` swaps `state_root` for
`receipts_root` and reaches a log instead of a slot.

`reader` links the library rather than calling `contract` across the ABI.
A cross-contract call would be the obvious shape and does not work:
`contract`'s historical arms *write* the period cache, so they are not
`staticcall`-able, and calling them mutably would make `reader`'s answer depend
on another contract's storage. Linking keeps the proof pure and the whole thing
one transaction.

## Which target carries what

| | EVM | native |
| --- | --- | --- |
| proof logic (`verife`) | ✅ | ✅ — 153 of 176 tests run on both |
| SHA-256 | precompile `0x02` | `core::hash`, software |
| Keccak-256 | the opcode | `core::hash`, software |
| anchor source | `Eip4788` (a `Call` effect) | `FixedAnchor` (no effect) |
| deployed contracts | `Verife`, `Reader` | — |
| the CLI | — | `verify`, `explain`, `calldata` |
| real mainnet trie proofs | `evm_mpt_tests` (7) | `verife` (17) |
| beacon→storage join | 1 unit test, plus a real transaction via `tools/reader_demo.sh` | 10 unit tests |

The ten EVM-only tests all compare a precompile or opcode against its software
twin, which is untestable natively by definition. The twenty-three native-only ones
are there because `fe test` deploys each ingot's suite as **one contract**, so
fixture byte arrays count against EIP-170 per ingot — the two beacon→storage
fixtures are 18 KB and 17 KB and do not fit. `evm_mpt_tests/` exists to give
the execution-layer fixtures their own budget; the join still has no EVM *unit*
test, only the on-chain transaction.

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
   SSZ ends here: everything above is fixed-arity containers hashed with
   SHA-256.

Steps 7 and 8 are a different world — Merkle-Patricia, Keccak-256, RLP, and a
format with several ways to write the same value:

7. **The account.** `state_root` is the root of the state trie. The key is
   `keccak256(address)`, 32 bytes, and the value is the account's four-field
   RLP: `[nonce, balance, storageRoot, codeHash]`.
8. **The slot, or the log.** `storageRoot` is the root of that contract's
   storage trie, keyed by `keccak256(slot)`. Swap `state_root` for
   `receipts_root` at step 6 and the same shape reaches a log instead —
   through a trie keyed by `rlp(index)` **unhashed**, which is why
   `mpt::lookup` takes a key length rather than assuming 32.

Every root after the first is the **return value of the previous step**. The
trie walk is handed the `state_root` that `prove_historical_payload_root`
returned, and the storage walk the `storageRoot` the account decoded. Nothing
downstream reads a constant, which is what makes this one chain rather than
two halves that happen to agree.

## Invariant 7, half of it in the type system

`dispatch.fe` holds the fork ordering. Two things follow from a *proven* slot:
`require_target_layout` checks that `T` is the layout of the fork the target
actually lived in, and `require_anchor_not_before_target` checks the anchor is
no earlier than the target.

Both take a `ProvenTarget`, not a `u64`, and that is the point: the only way to
obtain one is for `verify_recent`, `verify_historical` or `verify_in_period` to
have hashed a claimed header, found it equals a root reached from the anchor,
and found its slot equals the slot asked for. "Dispatch on an unproven slot" is
not a mistake this module can be talked into; it is one that does not type.

The ordering half no longer waits for run time. `AnchorFor<T>` is a marker
trait with no methods and no constants, implemented for the ten ordered
(anchor, target) pairs and none of the six impossible ones, and it is a bound
on every entry point that takes both:

```
error[6-0003]: trait bound is not satisfied
  `Capella` doesn't implement `AnchorFor<Fulu>`
  required by this bound on `prove_recent_payload_root`
```

An anchor state finalized in April 2023 cannot commit to a block from 2026 —
no branch exists that would satisfy it — and that is now a type error rather
than a revert after the proof has been built, encoded and sent. The impls are
listed rather than derived because Fe has no negative bounds, and pinned by ten
`static_assert`s against the same `order()` the runtime check uses, so the two
cannot drift. `require_anchor_not_before_target` stays as defence in depth,
now provable from the other two rather than load-bearing.

## Why the gindex math is `const fn`

Every position in that chain is derived from a layout type at compile time and
pinned with `static_assert`. Nothing is typed by hand and nothing is accepted
from a caller, so a proof built for the wrong fork's layout does not compile.
`docs/prior-art.md` records what this is a response to.

## The hashers — two of them, because two layers

The consensus layer hashes pairs of 32-byte chunks with SHA-256. The execution
layer hashes arbitrary byte strings with Keccak-256. Two traits, two
implementations each, selected by `#[cfg(target = ...)]`:

| Trait | Method | EVM impl | Native impl |
| --- | --- | --- | --- |
| `ChunkHasher` | `hash_pair(left, right)` | `PrecompileSha256` — precompile `0x02` | `SoftSha256` — `core::hash` |
| `ByteHasher` | `keccak(data)` | `EvmKeccak` — the opcode | `SoftKeccak` — `core::hash` |

The software implementations compile everywhere, so the core tests run them on
both backends. The EVM-only tests are the differential ones that cannot exist
natively: `both_hashers_agree`, `both_byte_hashers_agree` and
`the_keccak_opcode_and_the_software_one_walk_the_same_trie` each pin a
precompile or opcode against its software twin over the same input.

That is why `EvmKeccak` is `#[cfg(target = "evm")]` — and why even the `use`
of it has to be gated, or a native build fails to resolve the name.

Fe's std turned out to carry a whole SSZ module — `hash_pair`, `u64_chunk`
(little-endian `uint64` packing), `mix_in_length` and `Merkleize` — present
since Fe 26.2.0. VeriFe calls it rather than reimplementing the staticcall.
It lives under `std::evm`, so it is unavailable natively; that is the reason
the hasher is a trait with a `#[cfg]`-selected implementation rather than a
direct call.

**What is *not* a `const fn`:** neither hash. `core::hash::sha256_word` is an
ordinary function, so no hash can be folded at compile time —
`static_assert`ing a derived cryptographic constant is impossible, and
`EMPTY_TRIE_ROOT` and `KECCAK_EMPTY` are literals with tests behind them for
that reason. `docs/fe-findings.md` records it.

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
