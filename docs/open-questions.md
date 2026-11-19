# Open questions

Anything uncertain gets written down here rather than guessed at in code.

## 1. The per-fork layout table is unverified

The working notes for this project carry a table of field counts, depths and
gindices for Capella, Deneb, Electra and Fulu. It was drafted from memory of
the consensus specs.

**Before any of it becomes a layout type:** confirm every value against the
consensus-specs repository *and* an independent SSZ library (remerkleable or
`@chainsafe/ssz`), and pin each derived value with `static_assert`. Electra's
`historical_summaries` gindex of 91 should match Lido's published change from
59; that is a useful cross-check, not a source.

Status: **not started.**

## 2. Which hasher paths the std actually exposes — ANSWERED

Resolved by reading the std sources embedded in the `fe` binary:

| Path | What it gives | Where it runs |
| --- | --- | --- |
| `core::hash` | `Sha256` (FIPS 180-4), `sha256_word<T: HashInput>` | every backend |
| `std::evm::crypto::sha256` | precompile `0x02`, returns `Result<PrecompileError, u256>` | EVM |
| `std::evm::ssz` | `hash_pair`, `u64_chunk`, `mix_in_length`, `hash_tree_root`, `Merkleize` | EVM |

More than the design assumed: std ships SSZ merkleization, so VeriFe uses
`std::evm::ssz::hash_pair` on the EVM side instead of writing its own staticcall,
and `u64_chunk`/`mix_in_length` are already there for the little-endian `uint64`
leaves and the list length mix-in. Landed in `verife/src/hash.fe`.

A knock-on: the Monday roadmap item "upstream issue proposing std SSZ helpers"
no longer makes sense. If an upstream issue is worth filing, it should be about
`std::evm::ssz` being EVM-only when the merkleization itself is portable.

Status: **closed.**

## 3. Whether effects can carry the anchor source cleanly

The plan is to pass the anchor source as an effect (`uses (...)`) so that the
same verifier code runs against the EIP-4788 system call on chain and against
a fixture root in tests. Fe's effect system supports this in principle; the
shape it should take -- a trait, an effect-carrying struct, or a generic
parameter -- has not been settled.

Status: **design open.**

## 4. The Electra-anchor fixture may have to be synthetic

An Electra anchor needs an archived `BeaconState` from that fork window. If no
public endpoint still serves one, the fixture will be built with an independent
SSZ library and **labelled synthetic** in both the fixture file and the README.

Status: **unknown; depends on endpoint availability.**
