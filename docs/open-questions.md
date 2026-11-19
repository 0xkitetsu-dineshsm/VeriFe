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

## 2. Which hasher paths the std actually exposes

The design assumes `std::evm::crypto::sha256` on the EVM side and a software
SHA-256 in `core::hash` for native. The exact module paths in Fe 26.7.0 have
not been checked yet.

Status: **not checked.**

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
