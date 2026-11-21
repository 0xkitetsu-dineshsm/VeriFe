# tools

Supporting tooling. Not Fe, and declared as such in the README: the contest
requires the core technical contribution to be Fe, and this is not part of it.

| Tool | What it does |
| --- | --- |
| `compile_fail.sh` | Runs every `compile_fail/` ingot and requires it to still fail with its recorded diagnostic. `--bless` rewrites the expectations. |
| `layout_check.py` | Derives every field count, field position and gindex `layout.fe` pins from the `consensus-specs` container definitions, and checks them against the table this repo works from. `--cross-check` also diffs against an independent SSZ library. |
| `layout_cross_check.mjs` | The independent half: the same numbers out of `@lodestar/types` + `@chainsafe/ssz`, which define the containers by hand in TypeScript and compute gindices with their own tree code. |

Planned: the proof generator (fetches a finalized `BeaconState`, rebuilds a
period's 8,192 `block_roots`, emits fixtures).

## Verifying the layout numbers

```
cd tools && npm install          # once: pins @lodestar/types 1.51.0
python3 tools/layout_check.py --cross-check
```

Pinned sources: `consensus-specs` **v1.6.1** (the latest stable release;
`v1.7.0-*` are pre-releases carrying Gloas changes VeriFe does not implement)
and `@lodestar/types` **1.51.0**. Both are checked in `tools/package.json` /
the `--tag` default, so a drift in either is a test failure rather than a
surprise.

### Result, 2026-11-21: the working table is correct

Every value agrees across the spec markdown, this repo's table, and lodestar:

| Fork | `BeaconState` fields / depth | `fork` gi | `block_roots` gi | `historical_summaries` gi | body fields | payload fields | `payload.state_root` gi |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Capella | 28 / 5 | 35 | 37 | 59 | 11 | 15 | 18 |
| Deneb | 28 / 5 | 35 | 37 | 59 | 12 | 17 | 34 |
| Electra | 37 / 6 | 67 | 69 | 91 | 13 | 17 | 34 |
| Fulu | 38 / 6 | 67 | 69 | 91 | 13 | 17 | 34 |

Field positions, identical across all four forks: state `fork` = 3,
`block_roots` = 5, `historical_summaries` = 27; body `execution_payload` = 9
(gindex 25 in every fork, since 11, 12 and 13 fields all pad to depth 4);
payload `state_root` = 2, `receipts_root` = 3, `block_number` = 6,
`timestamp` = 9, `block_hash` = 12. `BeaconBlockHeader` has 5 fields (depth 3),
`Fork.current_version` is field 1 of 3, and
`HistoricalSummary.block_summary_root` is field **0** of 2 -- the field
security invariant 3 is about.

Composite gindices from a block body root to a payload field, which is what the
last leg of the proof walks: Capella 402 / 403 / 406 / 409 / 412 and
Deneb-onwards 802 / 803 / 806 / 809 / 812 for
`state_root` / `receipts_root` / `block_number` / `timestamp` / `block_hash`.
The Capella/Deneb split is the payload growing from 15 fields to 17, which
deepens it from 4 to 5 -- exactly the kind of silent shift that runtime pivots
get wrong and a `const fn` cannot.

## Data sources (surveyed 2026-11-21)

Every fixture has to say where it came from, so the survey behind that lives
here. All of these are keyless public endpoints; none is a dependency of the
library, only of fixture generation.

| Need | Endpoint | Finding |
| --- | --- | --- |
| headers, blocks, spec config | `https://ethereum-beacon-api.publicnode.com` | Full beacon API, keyless, and it serves slots back past Capella (slot 7,000,000 → 200). `/eth/v2/debug/beacon/states/` is **501 Not Implemented**. |
| finalized `BeaconState` (SSZ) | `beaconstate.ethstaker.cc`, `checkpointz.pietjepuk.net`, `mainnet-checkpoint-sync.attestant.io`, `mainnet-checkpoint-sync.stakely.io`, `mainnet.checkpoint.sigp.io`, `beaconstate-mainnet.chainsafe.io`, `testing.mainnet.beacon-api.nimbus.team` | All 200 on `/eth/v2/debug/beacon/states/finalized`, `application/octet-stream`. **None honours a `Range` request**, so any probe downloads the whole state: fetch it once, deliberately, into `tools/cache/` (gitignored). |
| — | `beaconstate.info` | Dead: no DNS answer. It is still listed in older notes; do not retry it. |

The checkpoint-sync list itself comes from
`eth-clients/checkpoint-sync-endpoints`, `endpoints/mainnet.yaml` on `main`.

### Spec constants, confirmed against a live node

From `/eth/v1/config/spec` on 2026-11-21, with the first slot computed as
`fork_epoch * SLOTS_PER_EPOCH` (32):

| Fork | `*_FORK_EPOCH` | First slot | `*_FORK_VERSION` |
| --- | --- | --- | --- |
| Capella | 194,048 | 6,209,536 | `0x03000000` |
| Deneb | 269,568 | 8,626,176 | `0x04000000` |
| Electra | 364,032 | 11,649,024 | `0x05000000` |
| Fulu | 411,392 | 13,164,544 | `0x06000000` |

`SLOTS_PER_HISTORICAL_ROOT = 8192`, `HISTORICAL_ROOTS_LIMIT = 16777216`
(2^24). All of these match the working layout table; the field counts and
gindices in that table are still unverified (see `docs/open-questions.md`).

### Three fork-activation slots are missed slots

Checked twice, against `/eth/v1/beacon/headers/{slot}` and
`/eth/v1/beacon/blocks/{slot}/root`, which agree:

| Slot | Block? | Note |
| --- | --- | --- |
| 6,209,535 | yes | last pre-Capella block |
| **6,209,536** | **no** | Capella's first slot — missed |
| 6,209,537 | no | missed |
| 6,209,538 | yes | first Capella block |
| 6,209,539 | no | missed |
| 13,164,543 | yes | last pre-Fulu block |
| **13,164,544** | **no** | Fulu's first slot — missed |
| 13,164,545 | yes | first Fulu block |

This is fixture material rather than trivia. `block_roots[s mod 8192]` repeats
the previous slot's root across a missed slot, so a proof "for slot 6,209,536"
reaches the block of slot 6,209,535 and the header it commits to says
`slot == 6209535`. Security invariant 10 (`header.slot == s`) is what makes the
verifier reject it, and these three slots are where that test should be built:
a fork's first slot being missed is the awkward case a fixture written from
round numbers would miss entirely.
