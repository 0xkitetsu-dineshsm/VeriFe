# fixtures

Mainnet proof fixtures. Each one is real beacon-chain data, and each one says
where it came from.

## What a fixture is allowed to contain

Headers, branches, indices, lengths and expected values. **Never a whole
`BeaconState`**: the state is 340 MB, it is not the project's output, and it
belongs in `tools/cache/` (gitignored) for as long as it takes to extract the
branches.

Every fixture records, under `provenance`:

| Field | Why |
| --- | --- |
| `beacon_api`, `state_endpoint` | Which node served the data. |
| `state_ssz_sha256`, `state_ssz_bytes` | Identifies the exact state the branches were cut from, so a fixture can be regenerated and compared byte for byte. |
| `generated_at` | The download date. |
| `consensus_specs`, `lodestar_types` | The versions whose layout numbers the gindices were derived from. |
| `synthetic` | `false` for real data. A fixture that had to be constructed says `true` here *and* in the README, per the contest rules. |

`expected_gindex` appears beside every branch. It is **not** an input to the
verifier: the Fe side derives each gindex from its layout type with `const fn`s
(security invariant 2). It is in the file so that a disagreement between the
generator and the Fe source fails loudly instead of silently verifying the
wrong node.

Branch order is leaf-first — `branch[0]` is the sibling at the leaf's own level
— which is what SSZ's `is_valid_merkle_branch` and every consensus client use,
and what `merkle::root_from_branch` expects.

## Generating and checking

```
cd tools && npm install
node --max-old-space-size=8192 gen_fixture.mjs recent --slot <s> --out ../fixtures/<name>.json
python3 tools/fixture_check.py fixtures/<name>.json
```

The second command is not a formality. `gen_fixture.mjs` builds fixtures with
`@lodestar/types` and `@chainsafe/persistent-merkle-tree`; `fixture_check.py`
re-derives every root with nothing but `hashlib`, and derives every gindex from
the consensus specs through `layout_check.py`. A fixture is only committed once
both agree, so no fixture rests on one library being right.

## What the first fixture establishes

`recent_fulu.json` is the whole recent path end to end, and every leg of it has
been checked twice:

* **Step 1, the anchor root.** `eth_call` to the real EIP-4788 contract at
  `0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02` with `t = 1795229027` returns
  `0x9fc57fac…`, which is the anchor block root. The fixture records the call
  and its answer, so the one trusted input is not taken on faith.
* **Step 2, the anchor header.** Its five fields hash to that root.
* **Invariant 8.** `state.fork.current_version` proven out of the anchor state
  in 8 levels (state depth 6 + `Fork` depth 2).
* **Step 4, recent.** `block_roots[128]` proven in 19 levels (6 + 13) to the
  anchor `state_root`.
* **Step 5.** The target header hashes to that leaf, and its `slot` is 15,696,000
  exactly — not a missed slot's repeat.
* **Step 6.** All five payload fields proven from the target `body_root` in 9
  levels (body depth 4 + payload depth 5), at gindices 802, 803, 806, 809 and
  812, with `block_number` and `timestamp` decoding little-endian.

## The matrix

Required by CLAUDE.md: a Fulu anchor with targets in Capella, Deneb, Electra
and Fulu; each fork's first slot; a slot right after a missed slot; the first
and last slot of a period; recent and historical paths.

| Fixture | Anchor | Target | Path | Notes |
| --- | --- | --- | --- | --- |
| `recent_fulu.json` | Fulu, slot 15,700,416 | Fulu, slot 15,696,000 | recent | `block_roots[128]`; EIP-4788 `t = 1795229027`, confirmed against the live contract. |
| `missed_slot_fulu.json` | Fulu, slot 15,700,416 | slot 15,694,457 (**missed**) | recent, negative | The invariant-10 attack: a real branch at the claimed slot's own gindex, carrying slot 15,694,456's header. |

### The missed-slot fixture, and why it is the only isolating negative test

Inside a single 8,192-slot window, slot and vector index are one-to-one: two
slots share an index only when they are 8,192 apart, which does not fit in the
window. So for almost any wrong slot the gindex changes and the branch simply
fails -- the Merkle check subsumes the slot check, and a negative test built that
way proves nothing about `header.slot == s`.

A **missed slot** is the exception. `process_slot` writes the previous block's
root again, so `block_roots[s mod 8192]` and `block_roots[(s-1) mod 8192]` hold
the same root and two slots really do map to one entry. Everything a verifier
checks then passes for the wrong slot, and only invariant 10 rejects it.

The anchor state names its own missed slots offline -- `tools/find_missed.mjs`
scans `block_roots` for a repeated consecutive entry and found **33** in this
anchor's window. `missed_slot_fulu.json` is one of them, and removing the
`header.slot == target_slot` assert from `verify_recent` makes exactly one test
fail: `the_missed_slot_attack_is_rejected`.

### Fork-activation slots are missed slots

Worth knowing before writing the "fork's first slot" fixtures: slots 6,209,536
(Capella) and 13,164,544 (Fulu) have **no block**, and neither does 6,209,537.
The first Capella block is 6,209,538. See `tools/README.md` for how that was
checked. `block_roots[s mod 8192]` repeats the previous root across a missed
slot, so a proof "for slot 6,209,536" reaches slot 6,209,535's block, whose
header says `slot == 6209535`. Security invariant 10 is what rejects it, and
these slots are the natural fixture for that test.
