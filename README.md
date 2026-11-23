# VeriFe

**One Fe source compiles to an on-chain verifier and a native CLI that prove
what any post-Capella Ethereum block committed to — its `block_hash`,
`state_root` and `receipts_root`, a contract's storage slot, or an event it
emitted — from a single EIP-4788 beacon block root. A proof built for the wrong
fork's layout does not compile.**

The sentence that is hardest to say any other way: **one transaction returns a
USDC storage slot as it stood on 13 April 2023, from a November 2026 beacon
block root** — four hard forks and 3.6 years back, through
`BeaconState.historical_summaries` and then into the execution layer's own
Merkle-Patricia state trie. It runs against the **real** EIP-4788 contract on a
pinned fork of mainnet, for 585,409 gas, and every single-bit corruption of it
is refused: `tools/reader_demo.sh`.

Fe **26.7.0** exactly (`fe 26.7.0 (e6e6342)`). Apache-2.0. Built inside the Fe
Builders Challenge window, November 3–24 2026.

---

## For judges: one screen

Every row is a command. `./check.sh` runs all of them; it is the same script CI
runs, and it prints a `skip` **with a reason** rather than a pass when
something it needs is missing.

| Claim | Command | Result |
| --- | --- | --- |
| Everything below, in one command | `./check.sh` | ✅ `all good. 15 ok, 0 skipped` — **no API key needed** |
| It builds on the pinned toolchain | `fe --version && fe check` | ✅ `fe 26.7.0 (e6e6342)` |
| The suite passes on both backends | `fe test && fe test --backend native` | ✅ **169 EVM, 172 native** |
| **Real mainnet proofs on the EVM target, with the Keccak opcode** | `fe test -i evm_mpt_tests` | ✅ 5 real proofs; opcode and software hasher agree |
| **The whole chain, in one on-chain transaction** | `tools/reader_demo.sh` | ✅ April-2023 slot from the real EIP-4788, **585,409 gas**, 6 controls refused |
| **A storage slot from April 2023, from one beacon root** | `fe test --backend native -f april_2023` | ✅ USDC slot 0 at block 17,034,870 |
| **An event proven, and identified by its own hash** | `fe test --backend native -f weth_transfer` | ✅ topic 0 = `keccak256("Transfer(address,address,uint256)")`, hashed in the test |
| A recent block's slot, the same chain end to end | `fe test --backend native -f one_beacon_root_proves_a_contract` | ✅ 9 levels, 2 hash functions, 2 encodings |
| **A proof that stops early is refused, not read as absent** | `fe test --backend native -f stops_early` | ✅ the March 2025 Lido bug class, on a real proof minus its last node |
| An absent slot is *proven* absent | `fe test --backend native -f proven_absent` | ✅ what Optimism's audited verifier cannot do at all |
| A real mainnet payload from a real EIP-4788 root | `fe test -f the_mainnet_recent_path_verifies` | ✅ Fulu slot 15,696,000 from anchor 15,700,416 |
| **A block 3.6 years older, through `historical_summaries`** | `fe test -f the_first_capella_block_verifies_from_a_fulu_anchor` | ✅ the first Capella block, slot 6,209,538 |
| A target in every fork, from one anchor | `fe test -f the_historical_path_proves_the_first` | ✅ Capella, Deneb and Electra first blocks |
| The Lido-class missed-slot attack is rejected | `fe test -f the_missed_slot_attack_is_rejected` | ✅ a genuine branch for a missed slot, refused |
| …and the branch it offers is genuine | `fe test -f the_offered_branch_is_genuine` | ✅ so the rejection is the slot check, not a bad hash |
| **A wrong-fork proof is a compile error** | `tools/compile_fail.sh` | ✅ **7 cases**, each negative-controlled |
| Reading an anchor root without declaring the effect | `tools/compile_fail.sh` | ✅ `missing effect row \`S::E\`` |
| **An anchor older than its target does not compile** | `tools/compile_fail.sh` | ✅ `error[6-0003]: \`Capella\` doesn't implement \`AnchorFor<Fulu>\`` |
| **The anchor source, against the real EIP-4788 contract** | `tools/fork_check.sh` | ✅ 5 mainnet blocks on a fork; the one leg `fe test` cannot reach |
| **Proven values confirmed by the execution chain** | `python3 tools/payload_check.py fixtures/*.json` | ✅ 25 values across 3 forks of history |
| The layout numbers are not ours to get wrong | `python3 tools/layout_check.py --cross-check` | ✅ consensus-specs v1.6.1 **and** @lodestar/types agree |
| No fixture rests on one library being right | `python3 tools/fixture_check.py fixtures/recent_fulu.json` | ✅ every root re-derived with `hashlib` alone |
| The trie verifier agrees with an independent builder | `fe test --backend native -f every_random_trie` | ✅ 28 vectors, shapes no real proof covers |
| Every guard was checked by deleting it | `python3 tools/mutate.py verife/src/mpt.fe` | ✅ mutation-tested; what it found is in the module notes |
| **Both contracts build, and fit** | `fe build -i contract -i reader --emit runtime-bytecode` | ✅ `Verife` 20,771 and `Reader` 9,422 of 24,576 |
| A native CLI proves the same blocks | `./out/cli verify historical-capella` | ✅ five payload fields, same library |
| …and explains itself | `./out/cli explain historical-capella` | ✅ the chain leg by leg, with real gindices |
| …and emits the contract's calldata | `./out/cli calldata historical-capella` | ✅ 2,660 bytes anchored, **900 cached** |
| **Prove a block of *your* choosing** | `tools/prove.sh --slot N` | ✅ 6 steps, 4 independent parties agree |
| Deployed to a public testnet | — | ⛔ no public tx hash; see *Limitations* for why a fork is the better evidence |
| Gas against a Solidity baseline | — | ⛔ not measured |

The two ⛔ rows are the honest state of this commit. Everything ✅ was produced
by running the command shown.

**On the two backends.** `fe test` deploys each ingot's suite as its own
contract, so fixture byte arrays count against EIP-170 *per ingot*. The
execution-layer fixtures total ~69 KB and cannot share one — which is why
`evm_mpt_tests/` exists as a separate ingot with its own 24,576-byte budget,
and why real mainnet state-trie and receipts-trie proofs run on the **EVM**
target there with the Keccak opcode, including the truncated-proof refusal.
No proxy pattern is involved: the limit is on the test harness, not on anything
deployed. The remaining native-only fixtures are the two beacon-to-storage
joins, which are larger still. Recorded in `docs/fe-findings.md`.

---

## Two layers, one trusted input

Most of this project is SSZ: the consensus layer's fixed-arity containers,
SHA-256, and positions derived from a type. The last two legs are the
execution layer's Merkle-Patricia trie: Keccak-256, RLP, and a format with
several ways to write the same value. VeriFe spans both, which is what lets one
beacon root answer a question about a contract's storage:

```text
  EIP-4788 root for timestamp t              ← the only trusted input
    → BeaconBlockHeader (5 fields, SHA-256)
      → BeaconState.block_roots[slot mod 8192]         (recent, ~27 h)
        or historical_summaries[i].block_summary_root  (historical, since Apr 2023)
          → target BeaconBlockHeader
            → body.execution_payload.state_root        ── SSZ ends here
              → state trie: keccak256(address) → account RLP
                → account.storageRoot
                  → storage trie: keccak256(slot) → the value
```

Swap `state_root` for `receipts_root` and the same shape proves an event: the
receipts trie, keyed by **`rlp(index)` unhashed** rather than by a hash, down
to one log's address, topics and data.

Every root below the first is the **return value of the previous proof**.
Nothing downstream reads a constant, which is what makes this a chain rather
than a set of tests that happen to agree.

`reader`'s `proveHistoricalCapellaStorageSlot` is that entire diagram as one
entry point, and `tools/reader_demo.sh` runs it on a pinned fork of mainnet
against the real beacon-roots contract. It is two contracts rather than one
because `contract` is already 20,771 of the 24,576 bytes EIP-170 allows — but
the split is better than the single contract would have been, because it puts
the line between *proven* and *assumed* on a contract boundary instead of in a
comment. `reader`'s `readStorageSlot` takes a state root as an argument and
says so in its name; `proveHistoricalCapellaStorageSlot` proves the root it
walks.

---


## The problem

EIP-4788 puts a beacon block root in the EVM — but only for 8,191 slots, about
27 hours. Reaching anything older means chaining SSZ Merkle proofs through
`BeaconState.historical_summaries`, and every step of that chain depends on
where a field sits inside a container **whose shape changes at every hard
fork**. `BeaconState` went from 28 fields to 37 at Electra, which moved
`block_roots`' generalized index from 37 to 69 and `historical_summaries`' from
59 to 91.

In Solidity those positions are hand-written constants switched at run time.
Lido's CSVerifier pivots on a `PIVOT_SLOT` constructor argument; EigenLayer's
BeaconChainProofs on a `PECTRA_FORK_TIMESTAMP`. The constants are correct
because somebody checked them, and they stay correct because nobody edits them
wrong.

In 2025 a high-severity bug was found in Lido's
`processHistoricalWithdrawalProof`: it accepted a **caller-supplied generalized
index** and checked only that it sat somewhere beneath `historical_summaries`.
A `HistoricalSummary` has two fields — `block_summary_root` and
`state_summary_root` — so a proof could be made to land on the wrong one. The
full account is in `docs/prior-art.md`.

Both bug classes have the same shape: a position that should be a property of a
type is instead a number carried at run time.

## Approach

Make each fork's SSZ layout a **Fe type**, and derive every generalized index,
tree depth and proof length from that type with `const fn`, pinned by
`static_assert`. No gindex is written by hand, and none is ever a parameter.

`verife/src/layout.fe` is the centre of the project. A `ForkLayout` trait
carries five associated constants, and `Capella`, `Deneb`, `Electra` and `Fulu`
implement it:

| Fork | First slot | `fork.current_version` | State fields / depth | `block_roots` gi | `historical_summaries` gi | Payload fields | Recent proof length |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Capella | 6,209,536 | `0x03000000` | 28 / 5 | 37 | 59 | 15 | 18 |
| Deneb | 8,626,176 | `0x04000000` | 28 / 5 | 37 | 59 | 17 | 18 |
| Electra | 11,649,024 | `0x05000000` | 37 / 6 | 69 | 91 | 17 | 19 |
| Fulu | 13,164,544 | `0x06000000` | 38 / 6 | 69 | 91 | 17 | 19 |

Not one of those numbers is typed into the verifier. Each is derived from the
field counts by `const fn` and checked by about sixty `static_assert`s — and
the whole table is re-derived from the consensus specs by
`tools/layout_check.py` and cross-checked against `@lodestar/types`, which
hand-writes the same containers in TypeScript, so a bug in one source cannot
hide. The only runtime indices in the entire verifier are the summary index `i`
and the slot within a period, and both are bounds-checked against depths the
type fixes.

The chain of commitments — EIP-4788 root → anchor header → anchor state →
target root → target header → payload field — and the eleven security
invariants are in `docs/architecture.md`.

## The Fe highlight

**A proof's shape is part of its type, and the shape is computed by the
compiler.**

```fe
pub struct RecentProof<L: ForkLayout> {
    pub branch: [u256; block_root_proof_len<L>()],
}
```

`block_root_proof_len<L>()` is a generic `const fn` that reads `L`'s associated
constant for its `BeaconState` field count, takes `ceil(log2(...))` of it, and
adds the 13 levels of `Vector[Root, 8192]`. Fe evaluates it at a concrete type
and the result is an **array length**. So Capella's recent proof is 18 siblings
and Fulu's is 19 — not by assertion, but because the types say so.

Two mistakes a verifier author really makes therefore stop being runtime
concerns. Handing one fork's proof to another fork's verifier:

```
error[8-0000]: type mismatch
   ┌─ src/lib.fe:23:32
   │
23 │     let _ = verify_fulu(proof: capella_proof)
   │                                ^^^^^^^^^^^^^ expected `RecentProof<Fulu>`, but `RecentProof<Capella>` is given
```

And a branch of the wrong depth for its fork — security invariant 6:

```
error[8-0000]: type mismatch
   ┌─ src/lib.fe:18:44
   │
18 │     let _ = RecentProof<Capella> { branch: [0; 19] }
   │                                            ^^^^^^^ expected `[u256; 18]`, but `[u256; 19]` is given
```

Read that second diagnostic closely: **nothing in the source file says 18.**
The author wrote `RecentProof<Capella>` and `[0; 19]`. The `18` was computed by
the compiler from Capella's field count. A library where a proof is `bytes32[]`
cannot produce either error — both mistakes compile, deploy, and are caught at
run time if they are caught at all.

Both are in `compile_fail/`, where each case records its diagnostic verbatim in
`expected.txt`. `tools/compile_fail.sh` fails if a case compiles **or** if its
diagnostic changes, so these tests fail when they stop failing. The generated
mainnet fixtures emit typed proofs too, which makes each fixture
compiler-checked against the layout it claims.

### The second Fe mechanism: an associated effect row

The anchor root — the one trusted input — comes from a different place on each
target, and `AnchorSource` declares that difference as an **effect**:

```fe
pub trait AnchorSource {
    uses E
    fn root_at(self, timestamp: u64) -> u256 uses E
}
```

`FixedAnchor` binds `E` to nothing. `Eip4788` binds it to the EVM `Call`
effect, because fetching a root there is a `STATICCALL` to the beacon-roots
contract. A caller generic over the source forwards the row with `uses S::E`.

This is not decoration. It is what makes the **deployed** code path testable:
`fe test` has no beacon-roots contract and cannot send a call from the EIP-4788
system address, so a verifier that called the system contract directly could
only ever be compiled, never run. Because the source is a parameter,
`verife/src/prove.fe` runs the exact composed path the contract runs — against
real mainnet fixtures, on both backends, with both hashers — and `contract/`
adds nothing but the binding.

It also closes a hole a type system normally cannot see. A wrapper that reads
an anchor root without forwarding the row does not compile:

```
error[8-0106]: missing effect row `S::E` required by `root_at`
   ┌─ src/lib.fe:24:5
   │
24 │     source.root_at(timestamp)
   │     ^^^^^^^^^^^^^^^^^^^^^^^^^ `root_at` requires the row `S::E`
   │
   = a row whose implementation is not known here is forwarded: require it via `uses S::E`
```

So "fetch the anchor root" cannot be disguised as a getter — the compile-time
half of invariant 1. That case is `compile_fail/undeclared_anchor_effect`.

Smaller, and in the same spirit: the hasher is chosen by
`#[cfg(target = "evm")]` — the SHA-256 precompile at `0x02` on the EVM,
software SHA-256 natively — and the two are proven to agree on real mainnet
data, not just on vectors. And Fe checks a `msg` selector against the ABI types
of its fields, so the `uint256[19]` written in the contract's selector cannot
drift from the `[u256; 19]` the layout derives.

### The third mechanism: a trait whose *missing* impls are the proof

Invariant 7 says an anchor cannot prove a target from a later fork. An anchor
state finalized in April 2023 cannot commit to a block from 2026 — there is no
branch that would satisfy it. That was a runtime `assert!`, which is sound and
fires far too late: after the proof has been built, encoded and sent.

`AnchorFor<T>` is a marker trait with no methods and no constants, implemented
for the ten ordered `(anchor, target)` pairs and none of the six impossible
ones:

```fe
pub trait AnchorFor<T> {}

impl AnchorFor<Capella> for Fulu {}      // a Fulu anchor, a Capella target
// and no `impl AnchorFor<Fulu> for Capella` anywhere
```

```fe
pub fn prove_recent_payload_root<
    A: ForkLayout + AnchorFor<T>,
    T: ForkLayout, …
>
```

So the impossible pair is not rejected — it is unrepresentable:

```
error[6-0003]: trait bound is not satisfied
   │     let _ = prove_recent_payload_root<Capella, Fulu, _, _>(
   │             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ `Capella` doesn't implement `AnchorFor<Fulu>`
   │     A: ForkLayout + AnchorFor<T>,
   │                     ------------ required by this bound
```

The impls are written out rather than derived, because Fe has no negative
bounds — "every pair but these six" is not expressible — and they are pinned by
ten `static_assert`s against the same `order()` the runtime check uses, so the
trait and the ordering cannot drift. A fork added to `Fork` without its impls
makes every pair involving it fail to compile, which is the right failure.

### What the code actually uses, counted

Claims about "idiomatic use" are cheap, so here is the inventory, measured:

| Feature | Count | What it carries |
| --- | --- | --- |
| `const fn` | 51 | every gindex, depth and proof length |
| `static_assert` | 157 | those values pinned to consensus-specs v1.6.1 |
| `#[cfg(target …)]` | 187 | one source, two backends |
| traits | 5 | `ForkLayout`, `ChunkHasher`, `ByteHasher`, `AnchorSource`, `AnchorFor` |
| generic structs | 4 | a proof's `[u256; N]` length comes from a `const fn` |
| associated effect rows | 64 | the compiler proving the cached path makes no call |
| `#[selector = CONST]` | 20 | one definition per entry point, signature still type-checked |
| `compile_fail` ingots | 7 | each mistake above, with its exact diagnostic |

`docs/fe-findings.md` is the other half of that engagement: eighteen things
that pushing on Fe 26.7.0 turned up, including two the compiler and formatter
disagree about, each with a measurement and a workaround.

## Prior art, and what is new here

Credit where it is due; this is not the first on-chain historical verifier.

- **Lido CSVerifier** — the reference implementation of this proof shape, and
  the source of the `PIVOT_SLOT` pattern (LIP-27) that VeriFe replaces with a
  type parameter. Its 2025 historical-gindex bug is the bug class `layout.fe`
  is built to make unrepresentable.
- **EigenLayer BeaconChainProofs** — the other production implementation, with
  the `PECTRA_FORK_TIMESTAMP` pivot and the careful note that EIP-4788 returns
  the *parent* beacon block root.
- **Optimism Bedrock `MerkleTrie`** — audited, and it cannot prove that a slot
  is *empty*, so a zero balance or a missing account is unreadable with it.
  `mpt.fe` treats absence as a verdict for that reason.
- **Lido `StateProofVerifier`** — audited, and it accepts a proof whose node
  list stops early after a branch node, reading the slot as zero: the class
  Roman Agureev found in March 2025, disclosed with ChainSecurity.
  `a_proof_that_stops_early_is_refused_and_not_read_as_absent` is that bug as a
  test, on a real mainnet proof with its last node removed.
- **eth-historian** — Rust, off-chain only; overlapping proof construction, no
  on-chain verifier.

### What the anchor choice decides

Storage-proof verifiers are usually anchored on `BLOCKHASH`, which is the
cheapest correct thing to do and caps reach at **256 blocks — about 51
minutes**. EIP-2935 extends that to 8,191 blocks, roughly a day. Both are
execution-layer anchors: they give you a block hash, and from a block hash you
can reach a state root and then the trie.

A consensus-layer anchor is a different trade. EIP-4788 gives a beacon block
root rather than a block hash, which costs an extra five levels of SSZ before
you reach any execution data at all — and buys `historical_summaries`, which
commits to every finalized period since Capella. That is what turns 51 minutes
into **April 2023**, and it is the only reason to pay for the extra levels.

**What is new here is the span, and the mechanism.** VeriFe reaches both
layers: consensus-layer SSZ commitments, and then the execution-layer trie they
commit to. And the fork's layout is a type, so the proof's shape is computed by
the compiler and the mistakes that caused real incidents become build failures.

If a storage slot from the last hour is what you need, a `BLOCKHASH`-anchored
verifier is simpler, cheaper and entirely sufficient — use one. If you need a
slot from 2023, you need a consensus-layer anchor, and that is this.

## Architecture

```
verife/        core library: all proof logic, no storage, no I/O
  --- the consensus layer: SSZ, SHA-256, positions from a type ---
  layout.fe      ForkLayout trait, the four fork types, the typed proofs
  gindex.fe      const fn: depth, gindex, concat, bounds
  hash.fe        ChunkHasher (SHA-256) and ByteHasher (Keccak), two impls each
  merkle.fe      branch verification by gindex, vector and list elements
  ssz.fe         little-endian uint64 leaves, length mix-in
  header.fe      BeaconBlockHeader hashing
  verify.fe      the recent, historical and cached paths
  prove.fe       the paths composed, generic over the anchor source
  anchor.fe      AnchorSource: EIP-4788 on chain, a fixed root natively
  dispatch.fe    Fork, the boundary table, invariant 7 on proven slots
  cache.fe       the write-once rule for a stored period commitment
  abi.fe         one selector per entry point, and the calldata encoder
  --- the execution layer: RLP, Keccak-256, a hex-nibble trie ---
  rlp.fe         canonical RLP, read in place
  mpt.fe         Merkle-Patricia lookup: present, absent, or refused
  --- and the seam ---
  join.fe        one beacon root to a storage slot, in a single chain
contract/      EVM verifier — establishes roots from the one trusted input
reader/        EVM reader   — reads into a root; the composed entry point
cli/           native CLI — verify, explain, calldata; software hashing
compile_fail/  ingots that must NOT compile, each with its diagnostic
fixtures/      mainnet beacon fixtures; fixtures/mpt/ the execution-layer ones
tools/         generators, the independent checkers, prove.sh, fork_check.sh
bench/         Solidity baseline and the gas harness  (README only)
docs/          architecture, prior art, forward-compat, Fe findings
```

All proof logic lives in `verife` and nowhere else. `contract` and `cli` each
bind exactly two type parameters — the anchor source and the hasher — and call
the same `verife::prove` entry points the tests call. Neither contains a Merkle
branch walk, a gindex or a bound.

## Build and test

```sh
curl -fsSL https://raw.githubusercontent.com/argotorg/fe/master/feup/feup.sh \
  | bash -s -- --version v26.7.0
fe --version          # fe 26.7.0 (e6e6342)

./check.sh            # everything
./check.sh --fast     # skips the native backend and the Python/Node checks
```

| Layer | Command |
| --- | --- |
| Format | `fe fmt --check verife` (one ingot per call — `fe fmt` does not walk a workspace) |
| Types | `fe check` |
| Tests, EVM backend | `fe test` |
| Tests, native backend | `fe test --backend native` |
| Build the CLI | `fe build --backend native -i cli` |
| Must-not-compile suite | `tools/compile_fail.sh` |
| Layout numbers vs two external sources | `python3 tools/layout_check.py --cross-check` |
| Fixtures re-derived from `hashlib` | `python3 tools/fixture_check.py fixtures/<name>.json` (one per call) |
| Proven values vs the execution chain | `python3 tools/payload_check.py fixtures/*.json` |
| The anchor source vs the real EIP-4788 | `tools/fork_check.sh [--block N]` (needs `anvil`) |
| **The whole chain in one transaction** | `tools/reader_demo.sh` (needs `anvil` and `ETH_ARCHIVE_RPC`) |
| **Prove a block of your own** | `tools/prove.sh --slot N` (needs a `BeaconState`; see below) |

The Python steps need 3.11+; the cross-check needs Node 20 and
`cd tools && npm ci`; the fork checks need Foundry. Without any of them
`./check.sh` reports `skip` **and says what is missing** rather than passing.
CI installs all of it and fails if *anything* skips.

### No credentials needed, and nothing to configure

`./check.sh` reports **`all good. 15 ok, 0 skipped`** on a cold clone with no
API key, no account and no environment variable set.

Three of those checks fork mainnet at block 26,460,570 — two days deep, so
past the ~128 blocks a public endpoint keeps state for — which normally means
an archive provider and a key. They default instead to `https://eth.drpc.org`,
a keyless public archive endpoint, verified to serve state at that block and to
return the real EIP-4788 root `0x9fc57fac…` for the anchor timestamp. If it
rate-limits you, point them anywhere else:

```sh
export ETH_ARCHIVE_RPC='https://your-archive-endpoint'   # optional
./check.sh
```

**No key is read from a file in this repository, and none is committed.** The
only private key present is anvil's first well-known development account, used
against a throwaway fork.

Archive access is needed to *fork*, never to *verify*: the contracts take a
root and a proof and have no notion of a block's age. Generating a *new*
execution-layer fixture does need archive `eth_getProof` — see *Reproducing the
fixtures* below — but verifying every committed one does not.

### Reproducing the fixtures — you do not need to

Every fixture is committed: 11 JSON files and 10 generated Fe modules, about
886 KB. `./check.sh` verifies all of them and **downloads nothing**;
`fixture_check.py` recomputes every root from the committed JSON with `hashlib`
alone.

Making a *new* one is a different matter, and worth knowing before you try:

* **A finalized `BeaconState` is 340 MB**, gitignored (a beacon state must never
  be committed), and none of the seven checkpoint endpoints honours a `Range`
  request — so there is no cheap probe. It took 38 seconds. One state serves any
  number of proofs, which is why all the beacon fixtures share one anchor.
* **An EIP-4788 confirmation expires after 27.3 hours.** An older fixture's
  `eth_call` check therefore shows as a `skip` with its age, computed from the
  timestamp rather than read from the file — a `window_expired` flag in a
  fixture would be a way to opt out of a check.
* **The execution-layer fixtures need archive `eth_getProof`.** No keyless
  endpoint serves it at depth: flashbots refuses past ~128 blocks with
  `code 4444`, others 403 or rate-limit. Archive access is needed to *generate*
  a proof, never to verify one — `mpt::lookup` takes a root and a proof and has
  no notion of age. That asymmetry is the same one Lido's CSVerifier and
  EigenLayer's BeaconChainProofs rely on.
* **A historical fixture rebuilds a period**: 8,192 block-root requests, ~25
  minutes. A *recent* one needs no rebuild, because `block_roots` is a live
  field of the state — which is why `prove.sh` uses the recent path.

`tools/prove.sh --slot N` is the whole loop in one command, and the point is
that four independent parties vouch for the answer:

| Step | Who | In what |
| --- | --- | --- |
| build the proof | `gen_fixture.mjs` | JavaScript, `@lodestar/types` SSZ |
| re-derive every root | `fixture_check.py` | Python, `hashlib`, **no shared code** |
| confirm the values | `payload_check.py` | a live execution node |
| emit the Fe module and a test | `fixture_to_fe.py`, `prove.sh` | so no Fe is hand-written |
| **verify** | `fe test` | the Fe code under test |

The generated test carries its own control, `and_one_bit_off_the_anchor_root_does_not`,
because a proof that verifies means nothing unless flipping one bit of the
anchor makes it fail.

## Tests

**131 tests on the EVM backend, 138 on the native backend.** The two sets
differ in both directions and deliberately: the EVM run compiles the SHA-256
precompile, the Keccak opcode and the `std::evm::ssz` agreement tests; the
native run adds the execution-layer suite, whose fixtures cannot fit in an EVM
test contract (see the note under the judges' table).

The fixtures are real mainnet data, with provenance recorded in each file and
explained in `fixtures/README.md`:

| Fixture | Anchor | Target | Path |
| --- | --- | --- | --- |
| `recent_fulu.json` | Fulu, slot 15,700,416 | Fulu, slot 15,696,000 | recent, via `block_roots[128]` |
| `missed_slot_fulu.json` | Fulu, slot 15,700,416 | slot 15,694,457 (**missed**) | recent, negative |
| `historical_capella.json` | Fulu, slot 15,700,416 | Capella, slot 6,209,538 | historical, `historical_summaries[0]` |
| `historical_deneb.json` | Fulu, slot 15,700,416 | Deneb, slot 8,626,176 | historical, `[295]`, period 1053 |
| `historical_electra.json` | Fulu, slot 15,700,416 | Electra, slot 11,649,024 | historical, `[664]`, period 1422 |
| `recent_join.json` | Fulu, slot 15,712,608 | Fulu, slot 15,712,604 | recent; the seam to the execution layer |

Deneb and Electra both activated on an exact period boundary
(8192 × 1053 and 8192 × 1422), so each of those fixtures is at once a fork's
first block *and* a period's first slot — the two edges most likely to be off
by one. Their summary indices are what `summary_index` derives from the slot
(1053 − 758 and 1422 − 758), asserted rather than assumed.

And the execution-layer fixtures, in `fixtures/mpt/`:

| Fixture | Rooted at | What it proves |
| --- | --- | --- |
| `hist_join_mainnet.json` | block 17,034,870 (**Apr 2023**) | USDC's account and slot 0, and an absent slot |
| `join_mainnet.json` | block 26,472,715 | the same, at a recent block |
| `mpt_mainnet.json` | block 26,472,617 | account, present slot, absent slot, empty-storage account, **and a truncated proof** |
| `receipts_mainnet.json` | block 26,472,802 | a receipt and its 3 logs, from a locally rebuilt receipts trie |
| `trie_vectors.json` | 14 random tries | 28 vectors; **synthetic, and labelled so** |

Two notes on method, because they are the parts a reviewer should distrust
first:

**Mutation testing, honestly reported.** Deleting a guard and watching the
suite stay green is the only way to know a negative test tests anything. Doing
that found that all four of `verify_recent`'s guards could be removed with
every test still passing. Invariant 10 now isolates — building a real
missed-slot fixture from mainnet was what it took, and removing
`header.slot == s` fails exactly one test. The other three guards still do not
isolate, and `verify.fe` says so in comments, with the reason for each. The
historical `i < length` bound is in the same position: a past-the-end index
reaches a zero `block_summary_root`, so isolating it would need a preimage of
zero. These are documented as defence in depth rather than claimed as tested.

**The historical period is rebuilt, and the rebuild is checked.** No public
endpoint serves a historical `BeaconState`, so the period's 8,192 `block_roots`
are rebuilt from block headers, carrying the previous root across missed slots
exactly as `process_slot` does. The generator refuses to write a fixture unless
that rebuild hashes to the `block_summary_root` the anchor state commits to, and
`fixture_check.py` then re-derives it independently. Wrong by one slot and no
fixture exists.

## Cost

**No gas number has been measured**, and there is no table here because there
is no figure we have run. `bench/` holds only its README and the intended
method.

What *is* measured is calldata, by `./out/cli calldata`, and it is the part
that dominates a proof's cost on L1:

| Call | Calldata | Needs |
| --- | --- | --- |
| `proveHistoricalCapellaBlockHash` | **2,660 bytes** | an anchor, a fork proof, two summary branches, an EIP-4788 call |
| `proveCachedCapellaBlockHash` | **900 bytes** | a stored period commitment, and no system call |

So a cached period is 66% less calldata and no `STATICCALL` for the same proven
block hash. That is the honest argument for the cache — see
`docs/forward-compat.md`, which also corrects an earlier overstatement of mine
about what it saves at a fork.

## Limitations

Listed in the order a reviewer should care about them.

- **No public tx hash.** Both contracts build and fit (20,771 and 9,422 of
  24,576) and the whole chain runs as a real transaction for 585,409 gas — but
  on a *pinned fork* of mainnet, not a public network, so there is no link to
  click and no demo recording in this commit. That is a presentation gap rather
  than an evidence gap, and deliberately so: a Sepolia deployment could not
  validate any of this, because Sepolia's EIP-4788 holds *Sepolia's* beacon
  roots and a mainnet anchor root is simply not in it. The fork exercises the
  real system contract with real mainnet history and is reproducible by block
  number for as long as an archive node serves block 26,460,570.
- **The demo needs an archive endpoint, and will not read a key from this
  repo.** `ETH_ARCHIVE_RPC` or nothing; `./check.sh` skips that check with
  that reason. Archive access is needed to *fork*, never to verify — `reader`
  takes a root and a proof and has no notion of age.
- **`reader` has one composed entry point, for a Fulu anchor and a Capella
  target.** Deneb and Electra targets are provable by the library and have no
  composed arm; each is a few lines plus a fixture.
- **No gas number.** See *Cost* above. Calldata is measured; execution gas is
  not.
- **`ExtraNodes` is not enforced.** An MPT proof carrying nodes beyond the path
  is accepted, because the value is still proven by the path that was walked. A
  malleability wart rather than a soundness hole, and recorded in `mpt.fe`.
- **The contract is at 85% of EIP-170.** 20,771 of 24,576 bytes. One
  monomorphised arm per (anchor, target, field) does not scale much further —
  the real cost of the named-entry-point design. A `uint256[]` dispatch would
  trade the compile-time branch-length check for size, and belongs *alongside*
  the typed arms rather than replacing them. The MPT reader will not fit beside
  this and should be a second contract, which also makes the trust boundary
  explicit.
- **The CLI's proofs are compiled in, not parsed at run time.** `./out/cli
  verify historical-capella` runs the real library over real mainnet fixtures,
  but they are generated Fe modules rather than JSON read at startup.
  `tools/prove.sh` hides the rebuild, but it is a rebuild. A run-time JSON
  parser is the obvious next step and is itself code that can be wrong.
- **The anchor fork is pinned at compile time.** `type ANCHOR = Fulu`, and
  invariant 8 makes the chain agree, so at Glamsterdam the anchor-based entry
  points revert rather than mis-verify — the trade this project argues for
  against Lido's `PIVOT_SLOT` and EigenLayer's `PECTRA_FORK_TIMESTAMP`.
  **Correcting an earlier claim of ours:** the cache does *not* rescue history
  that would otherwise be lost. EIP-7732 changes the block body, not
  `BeaconState.historical_summaries`, so a verifier recompiled for the next
  fork's anchor layout reaches the same old periods from a fresh anchor. What
  the cache buys is a 66%-cheaper query, no live-anchor dependency, and no
  redeployment — stated properly in `docs/forward-compat.md`.
- **The cache is the one exception to invariant 1, written down rather than
  glossed.** A stored summary root is a second thing a proof can start from. It
  is not an *input*: only a complete historical proof can admit one, the entry
  is write-once, zero means "nothing stored", and there is no owner and no
  administrative write. The rule lives in `verife/src/cache.fe` — in the
  library rather than the contract precisely so `fe test` can reach it, since
  nothing in a `recv` arm can be.
- **Gloas / ePBS is not implemented, by design.** It is a stated non-goal, and
  Glamsterdam *is* the Gloas fork: EIP-7732 removes `execution_payload` from
  `BeaconBlockBody` entirely and EIP-7688 makes the containers progressive, so
  step 6 of the chain above ceases to exist and `field_gindex(field,
  field_count)` is the wrong formula for the new ones. That needs new code, not
  new constants, and the spec is not frozen. Invariant 8 fails closed on an
  unrecognised fork version, and `dispatch.fe`'s exhaustive `match` means Gloas
  cannot be silently treated as Fulu.
- **Pre-Capella is a hard boundary.** `historical_summaries` begins at slot
  6,209,536 (April 2023); invariant 9 refuses anything earlier. "Any historical
  block" means any post-Capella block.
- **One guard class is defence in depth, not tested in isolation.** Mutation
  testing found that all four of `verify_recent`'s guards could be deleted with
  the suite still green. Invariant 10 now isolates — building a real
  missed-slot fixture from mainnet was what that took. The other three still do
  not, and `verify.fe` says so in comments with the reason for each. The
  historical `i < length` bound is the same: a past-the-end index reaches a
  zero `block_summary_root`, so isolating it would need a preimage of zero.
- **One synthetic fixture, labelled.** `fixtures/mpt/trie_vectors.json` says
  `synthetic: true` and exists to reach trie *shapes* no real proof covers.
  Every other fixture is real mainnet data. No Electra-*anchor* fixture exists,
  because no public endpoint serves an Electra-window state.
- Out of scope, deliberately: validator, balance and withdrawal proofs (Lido
  and EigenLayer cover those), and EIP-2935 / header-RLP proofs.
- **Not audited.** Nothing here is production code. Beacon roots before
  finality can be reorged; a consumer should require finality depth, which this
  library does not do for you.

## Declaration

- **Pre-existing work:** none. The repository starts from the Fe Builders
  Challenge starter (commit `f9d9aa9`); its example vault contract and
  `SUBMISSION.md` template were removed in the first VeriFe commit. Everything
  else was written inside the build window.
- **Third-party code:** none vendored into the Fe sources. The proof generator
  in `tools/` uses `@lodestar/types` 1.51.0 and
  `@chainsafe/persistent-merkle-tree` 1.3.1 (pinned in
  `tools/package-lock.json`) to build fixtures, and
  `ethereum-cryptography` (a transitive dependency already present) for
  Keccak-256 when rebuilding a receipts trie. `tools/layout_check.py` and
  `tools/fixture_check.py` re-derive the same values from the consensus specs
  and Python's `hashlib` to check them, sharing no code with the generators. The design
  responds to Lido's CSVerifier and EigenLayer's BeaconChainProofs; no code is
  copied from either.
- **AI assistance:** Claude (Claude Code) was used throughout — for repository
  structure, drafting Fe and documentation, deriving the layout numbers, and
  checking Fe syntax against the compiler. Every compiler and test claim in
  this README was produced by running the command shown, not by asking a model
  what it would print.

## License

Apache-2.0. See `LICENSE`.
