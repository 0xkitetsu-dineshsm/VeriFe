# Surviving the next fork

VeriFe pins its anchor layout at compile time (`type ANCHOR = Fulu` in
`contract/src/lib.fe`) and proves `state.fork.current_version` against it
(invariant 8). When Glamsterdam activates, that check stops passing and the
anchor-based entry points revert.

That is the intended failure. Lido carries a `PIVOT_SLOT` and EigenLayer a
`PECTRA_FORK_TIMESTAMP`; both are runtime constants that are *wrong* for a
window around a fork, and being wrong about a layout means verifying a proof
of the wrong node. Here the fork is a type and the failure is a revert.

But "reverts rather than lies" is not the same as "keeps working", and for
anything already final it should not have to be the choice. This document
separates the parts of the problem that are solvable from the one that is not,
and records which are built.

## Anchor fork and target fork are different problems

| | Anchor fork | Target fork |
|---|---|---|
| What it is | the fork live *now*, because the anchor comes from EIP-4788 | the fork the proven block lived in |
| What it governs | `BeaconState`: where `fork`, `block_roots` and `historical_summaries` sit | `BeaconBlockBody` and `ExecutionPayload` |
| Direction | forward: it changes under you | backward only: frozen history |

The target side is finishable and finished in principle: compile in every past
layout and it never needs another change. Forward compatibility is purely an
anchor-side problem.

Narrower still. `ForkLayout` is five consts, and the anchor role reads two:

| Const | Anchor | Why |
|---|---|---|
| `STATE_FIELDS` | **yes** | every state-side gindex derives from `depth(STATE_FIELDS)` |
| `VERSION` | **yes** | invariant 8's equality |
| `BODY_FIELDS`, `PAYLOAD_FIELDS`, `FIRST_SLOT` | no | target-side only |

And gindices depend on `STATE_FIELDS` only through `depth()`. Electra has 37
fields and Fulu 38 -- both depth 6, so their state gindices are identical (69
and 91 for both). If Glamsterdam lands anywhere in 33-64 state fields, the
geometry does not move and `Fulu`'s state layout is still correct.

**On the most likely outcome, the only thing that breaks is one equality
check.** Not the Merkle math.

## What is impossible

Proving a block mined *after* an unspecified fork. If its `ExecutionPayload`
gains a field the tree deepens and every field's gindex moves, and no code
deployed today can recover an unpublished number. Any claim otherwise would be
false, and it is not a Fe limitation.

## Built: the period cache

**Status: implemented.** `verife/src/cache.fe`, `verify_in_period` and
`prove_cached_*` in `verife/src/prove.fe`, `proveCached*` in
`contract/src/lib.fe`.

`historical_summaries` is append-only and the periods in it are finalized. A
`block_summary_root` is the hash tree root of 8,192 finalized block roots, so
proving one is a statement about finalized history -- permanently true. The
contract stores every one it proves, and `proveCached*` starts from a stored
root:

* no EIP-4788 call -- and the arms do not declare `uses (call)`, so the
  compiler is what says so. Checked by removing the claim rather than
  trusting it: adding `Eip4788 {}.root_at(...)` to a cached arm gives

  ```
  error[8-0036]: missing effect `Call` required by `root_at`
      ┌─ src/lib.fe:467:21
      │
  467 │             let _ = sneaky.root_at(timestamp: target_slot)
      │                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ `root_at` requires effect `Call` to be in scope
      │
      = require it in this function's signature with `uses Call`, so that its callers provide it
  ```

  A Solidity equivalent would have to be established by reading the function
  and everything it calls;
* no fork-version check, because no anchor is involved;
* no `A: ForkLayout` parameter at all. The period leg is a `Vector[Root, 8192]`
  and 13 levels in every layout, and the payload leg is the *target's* layout.

So every block in a cached period stays provable after Glamsterdam, with no
redeployment and no new key. The operational requirement is that caching
happens while a known-fork anchor is live; it is a free side effect of every
historical proof, so normal use fills it.

### The trust change, stated plainly

A stored root is a second thing a proof can start from. Invariant 1 is
restated, not stretched:

> The anchor root is the only trusted **input**. A stored summary root is not
> an input: it is a value this contract proved from an anchor root in an
> earlier transaction, admitted by one code path, write-once, and never read
> from calldata.

Three properties carry it, all in `verife::cache::admit_summary_root` and all
tested on both backends:

1. **Only a full proof admits a value.** The only `proven` in existence comes
   from `verify_historical`: EIP-4788 root, anchor header hashed against it,
   `fork.current_version` proven, list length proven through the mix-in, index
   bounded by it, branch landing exactly on `block_summary_root` at exactly its
   depth. No cheaper path in, and no administrative one -- there is no owner.
2. **Write-once.** An admitted value can never become a different value
   (`a_written_period_cannot_be_rewritten`, `a_written_period_cannot_be_cleared`).
   Every proof built on a stored root would be retroactively wrong otherwise,
   so this is the property the design rests on. Re-proving the same period is
   accepted and changes nothing, which it must be: two blocks in one period are
   two proofs reaching one root.
3. **Zero is not a value.** A `StorageMap` miss reads as zero, so zero means
   "nothing stored" and the cached path refuses it.

## Designed, not built: a self-validating fork registry

**Status: specified here, deliberately not implemented.** It would close the
live window too -- recent blocks across a fork, no redeployment, no privileged
key -- and it needs adversarial tests against a fork that does not exist yet.
Shipping it unverified would contradict the argument this project makes.

Replace the compiled-in anchor constant with a **write-once, permissionless
registry**, where registering a fork means *proving* its numbers against
values the registrant does not control:

| Number to learn | Probe | Compared against |
|---|---|---|
| `VERSION` | prove the `Fork` container and read both fields | `fork.previous_version` must equal the already-registered fork's `VERSION`, chaining back to compiled-in Capella. `current_version` is **discovered**, never asserted |
| `depth(STATE_FIELDS)` | prove `block_roots[(S-1) mod 8192]` | `anchor_header.parent_root`, already proven in step 2 by hashing the header against the EIP-4788 root |
| `depth(BODY_FIELDS)`, `depth(PAYLOAD_FIELDS)` | prove `payload.block_hash` of a block in the last 256 | `ctx.blockhash(n)`, the EVM's own opcode |

The soundness argument is the same in every row: the comparison value is fixed
by the chain, not by the registrant. A wrong candidate depth gives a wrong
gindex, a wrong path and a different root, so passing a probe with a wrong
number means producing a SHA-256 second preimage of a root you do not control.
Candidate depths are small and bounded, so an honest registrant submits the
right one and nobody else can submit any other.

Each fork then costs **one permissionless transaction by anyone**, with the
contract as the only verifier.

Two notes on feasibility, both checked rather than assumed:

* `ctx.blockhash(n)` exists on Fe's `Ctx` effect (`std/src/evm/effects.fe`).
* **A Fe `const fn` is callable with runtime arguments.** Verified by spike:
  `depth(leaves: runtime_value)` compiles and agrees with the same call in a
  `const`. So `gindex.fe` needs no runtime twin -- the identical functions
  serve a compile-time and a registered layout, which is most of why this
  design is affordable at all.

### What it would cost

Depths become runtime values, which brushes invariant 2 ("no caller-supplied
gindex"). The two paths should stay visibly separate:

* **compiled-in forks stay compile-time**, with `static_assert`, typed branch
  lengths and all six `compile_fail` cases intact. This remains the primary,
  documented path;
* **the registry is a labelled fallback**, reachable only for a fork with no
  compiled-in layout, and its invariant 2 is "caller-*proposed*,
  chain-validated, write-once" -- which should be written in those words and
  not claimed as the same guarantee.

Fail-closed survives throughout: if a fork renames `historical_summaries`,
restructures `Fork` or changes `BeaconBlockHeader`, every probe fails and
nothing registers.

### It may all become unnecessary

EIP-7688 progressive containers give each field a stable gindex in a sparse
tree, so field counts stop moving anything and forward compatibility is free.
If the ePBS/Gloas direction lands, the registry is dead code -- a good outcome
to have predicted in writing.

## Summary

| Goal | Status |
|---|---|
| Fail closed rather than mis-verify at a fork | built (invariant 8) |
| Every block up to the last cached period, after any fork, no redeploy | **built** (the period cache) |
| Recent blocks across a fork, no redeploy | designed above, not built |
| Blocks mined after an unspecified fork | impossible by construction |
