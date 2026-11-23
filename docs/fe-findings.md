# Fe findings

Things learned about Fe 26.7.0 while building VeriFe. Findings that look like
compiler bugs get a minimal reproduction here first; some may become upstream
issues.

## `static_assert` takes one argument and no `!`

It is `static_assert(expr)`, not `static_assert!(expr, "message")`. Writing the
`!` gives `error[1-0001]: expected static assertion`, and a second argument
gives `missing closing ')' for static assertion`. The diagnostic on a failure
is excellent -- it prints the two sides and the operator:

```
error[8-0081]: static assertion failed
  = left: `3`
  = right: `4`
  = operator: `==`
```

Not a bug; worth documenting, because the `!` spelling is the natural guess.

## `assert!` inside a `const fn` fires at compile time

A failing `assert!` in a `const fn` evaluated in a `const` context produces
`error[3-0073]: assertion failed in const context`, with the call site and the
assertion both in the span. This is what the whole `compile_fail/` suite rests
on: bounds checks written once in `gindex.fe` turn layout mistakes into build
failures. See `compile_fail/field_past_end/expected.txt`.

## Corrections after checking the Fe issue tracker (2026-11-21)

Two notes here were stale, and the tracker says so:

* **EIP-170.** "`fe build` does not warn when runtime code exceeds 24,576
  bytes" was filed as #1951 and fixed by #1956, both closed. CI should still
  check the size itself, but the claim that Fe is silent needs re-testing
  against 26.7.0 before it is repeated anywhere public.
* **`.downcast_truncate()` in `assert!`.** The problem is not a grammar
  restriction on turbofish. The method takes *no* generic arguments at all
  (`error[8-0022]: too many generic arguments`), so its type comes only from
  inference, and `x.downcast_truncate() > 0` genuinely does not determine one.
  A `let` with an annotation is the idiomatic answer, not a workaround for a
  bug. Not worth filing.

Drafts of what *is* worth filing are in `docs/upstream/`.

## `fe fmt` does not walk a workspace

`fe fmt --check` at a workspace root reports `Error: No .fe files found`, and
it takes a single `PATH`, so several ingots cannot be checked in one call. CI
loops over the members instead. Candidate upstream issue: `fe fmt` could
resolve workspace members the way `fe check` and `fe test` do.

## Arguments are labelled by default

`double(x)` is an error when the parameter is named `x`; it must be
`double(x: x)` or the parameter declared `_ x: u64`. Worth knowing before
writing a module full of small numeric helpers.

## `#[cfg(target = ...)]` works per backend — but one member can pin a workspace

Two findings, and the second nearly cost us a whole half of the test suite.

**The good half.** `#[cfg(target = "evm")]` is resolved from the backend the
build is actually using, not only from `target` in `fe.toml`. `verife/fe.toml`
declares no target, yet

```sh
fe test                  # 12 passed -- EVM-only items compiled in
fe test --backend native # 10 passed -- EVM-only items compiled out
```

The counts differ by exactly the two `#[cfg(target = "evm")]` tests, and a
`use std::evm::ssz` under the same attribute is simply not resolved on the
native backend. That is what lets one library compile for both targets.

**The trap.** A single workspace member with `target = "native"` in its
manifest pins *every* member to native. `cli/fe.toml` originally set it, being
a native binary, and the effect was that workspace-wide `fe test` compiled
`verife` as native too:

```sh
fe test                  # 10 passed  <-- silently NOT the EVM backend
fe test -i verife        # 13 passed  <-- the EVM arms, only per-ingot
```

Nothing warned. `fe test` and `fe test --backend native` returned identical
results, both green, and the precompile hasher was never executed. CI would
have reported a fully passing suite while never once calling precompile `0x02`.

A related sharp edge: `fe test -f <name>` exits 0 after running nothing when
the filter matches nothing, so a filter that silently stopped matching -- for
this exact reason -- looks like success.

The fix here was to drop `target` from `cli/fe.toml` and build the binary with
`fe build --backend native -i cli` instead, which leaves the workspace free to
be compiled for either target. Candidate upstream issue: a member's `target`
should not silently become the workspace's, or `fe test` should say which
target each member was built for.

## std already ships SSZ merkleization

`std::evm::ssz` provides `hash_pair`, `u64_chunk` (little-endian `uint64`
packing), `mix_in_length` (the `List[T, N]` length mix-in), `hash_tree_root`
and a `Merkleize` trait covering tuples of arity 1 to 16 — written for the
deposit contract, but these are the generic SSZ primitives. `hash_pair` reuses a
single 64-byte scratch buffer across the staticcall's read and write and checks
`returndatasize`, so VeriFe calls it rather than reimplementing it.

The limitation worth raising upstream: this is all under `std::evm`, so none of
it is available natively, even though merkleization itself has nothing
EVM-specific about it. Only the SHA-256 call does. A portable `ssz` module over
a hash function would serve any consensus-layer tooling built in Fe.

## `core::hash::Hasher` is taken

`core::hash` already defines a `Hasher` trait — the `HashMap` one, which writes
words and finishes to a `u64`. VeriFe's SSZ chunk hasher is called
`ChunkHasher` to stay out of its way.

## `fe fmt` writes `0 .. 32`, not `0..32`

Purely cosmetic, but `fe fmt --check` fails on the compact form, so it is worth
knowing before writing a file full of loops.

## `static_assert` cannot see a const generic parameter

The appealing design for the branch walk was to check the proof length against
the gindex *at compile time*:

```fe
pub fn root_from_const_branch<H: ChunkHasher, const GI: u64, const N: usize>(
    hasher: H, leaf: u256, branch: [u256; N],
) -> u256 {
    static_assert(gindex_depth_len(gi: GI) == N)
    ...
}
```

`const GI: u64` is accepted (non-`usize` const params are fine), and the
`static_assert` parses, but it does not compile:

```
error[8-0090]: const value must be resolvable during type checking
    │     static_assert(gindex_depth_len(gi: GI) == N)
    │                                       ^^ requires value `const GI: u64`
```

So `static_assert` is evaluated during type checking, before monomorphization,
and cannot see the value a const generic will be instantiated with. The
guarantee is still available one level up -- a caller writes
`static_assert(gindex_depth_len(gi: GI) == 13)` beside its concrete `const GI`
-- which is where VeriFe puts it, with the runtime length check inside the walk.
Candidate upstream issue: a post-monomorphization `static_assert` would let a
library express "this array's length must match this index's depth" once,
instead of asking every caller to restate it.

## `assert!` and `static_assert` reject turbofish in their arguments

Both take a restricted expression grammar. A `::<T>` anywhere inside produces a
parse error that points at the `:` and blames a missing `)`:

```
error[1-0001]: missing closing `)` for static assertion
    │     static_assert(gindex_depth(gi: GI).downcast::<usize>() == N)
    │                                               ^ expected `)` or `,`
```

Bind the value to a local first, then assert on the local.

## `usize` and `u64` do not convert with `as`

`usize` is as wide as the target's memory, so neither direction is provably
lossless and `as` is rejected both ways; `.downcast_truncate()` works but
cannot be written inside `assert!` (above). Where a `const fn` needs to produce
a length, the clean answer is to recurse in `usize` and avoid the conversion
altogether -- `gindex_depth_len` returns `usize` while taking a `u64`, with no
cast anywhere in its body.

## Three mutation findings, recorded because the tests were wrong first

While checking that the negative tests actually test something:

1. **The two length guards in `root_from_branch` are equivalent.** Walking `N`
   levels from `gindex` ends at `gindex >> N`, which is 1 exactly when `N` is
   the depth. Removing the explicit length check left every test green, because
   the `level == 1` backstop catches the same inputs. Both are kept -- one
   avoids paying for `N` hashes, the other survives a rewrite of the loop --
   but no behavioural test can tell them apart, and the tests now say so
   instead of claiming to target one.
2. **An all-zero tree cannot detect an inverted side selection.** Every node's
   children are equal, so `zero_tree_matches_the_published_zero_hashes` passes
   with the sides swapped. Inverting the comparison showed that only the tests
   with distinct leaves catch it. The comment claiming otherwise was wrong and
   has been corrected.
3. **`a_capacity_that_is_not_a_power_of_two_is_rejected` passed for the wrong
   reason.** Removing the power-of-two guard from `element_position` left every
   test green: with `capacity: 6` the element lands at node 12, whose depth is
   3, and the four-sibling branch the test passed was then refused by the
   proof-length check instead. The test was shortened to a three-sibling branch
   -- the length node 12 really wants -- so that the power-of-two guard is the
   only thing that can reject it, and re-mutating now fails it. The lesson
   repeats: a `should_revert` test proves nothing until the code it targets has
   been removed and the test watched to fail.

## `tools/compile_fail.sh` normalized nothing for two commits

The line-number normalizer matched an ASCII `|` where Fe's diagnostics use the
box-drawing `│`, so it was a no-op; it went unnoticed because no expectation
had shifted yet. Adding a function above `field_gindex` moved it and the case
failed on line numbers alone. Fixed to match the real character, including the
multi-line `│ ╭` / `│ │` gutter forms, and verified in both directions: a
shifted file still passes, a changed message still fails.

## A trait associated const *can* be seen at compile time, a const generic cannot

This is the finding the whole layout design rests on, and it is the other half
of "`static_assert` cannot see a const generic parameter" above.

`static_assert` runs during type checking, before monomorphization, so it
cannot see the value a `const N: usize` parameter will be instantiated with.
But an **associated const on a trait**, read through a concrete type, resolves
right there:

```fe
pub trait ForkLayout { const STATE_FIELDS: u64 }
pub struct Capella {}
impl ForkLayout for Capella { const STATE_FIELDS: u64 = 28 }

pub const fn block_roots_gindex<L: ForkLayout>() -> u64 {
    field_gindex(field: 5, field_count: L::STATE_FIELDS)
}

static_assert(block_roots_gindex<Capella>() == 37)   // compiles, and is checked
```

Three things had to hold for this to work, and all three do in 26.7.0:

1. A trait may declare associated consts, and an impl may define them.
2. A **generic `const fn`** may read `L::CONST` and be evaluated in a const
   context at a concrete `L`. (It must be declared `const fn`: a plain `fn`
   gives `error[3-0024]: non-const function call in const context`.)
3. The result may be an **array length**: `[u256; block_root_proof_len<L>()]`
   is accepted, so a struct's shape can be derived from its type parameter.

Point 3 is the one that surprised me, and it is what makes the central claim of
this project real rather than aspirational. A proof type carries its fork, and
its branch length is computed from that fork's field count, so both of these
are type errors:

```
expected `RecentProof<Fulu>`, but `RecentProof<Capella>` is given
expected `[u256; 18]`, but `[u256; 19]` is given
```

Nothing in the failing source says 18. Security invariant 6 is therefore
enforced by the type checker at every boundary, with the runtime length check
in `root_from_branch` kept only for branches assembled dynamically.

Turbofish is spelled `f<T>()` here, not `f::<T>()`: writing the Rust form gives
`error[1-0001]: unexpected turbofish syntax ::<; remove the double colons`.

**Upstream value:** the asymmetry is worth raising, not as a bug but as a
documented recommendation. "Carry compile-time facts as trait associated
consts, not as const generic parameters, if you want `static_assert` to see
them" is a rule a library author currently has to discover by experiment. A
post-monomorphization `static_assert` would remove the need to know it.

## `fe test` deploys the EVM suite as one contract, so test *data* hits EIP-170

Found 2026-11-22 while adding a fourth execution-layer fixture.

The EVM test backend deploys the whole test suite as a single contract. Byte
arrays in test fixtures are compiled into that contract's code, so they count
against the 24,576-byte EIP-170 limit along with the code under test. Four
`eth_getProof` fixtures (about 1,250 lines of `[u8; N]` each) pushed the suite
over, and the failure surfaces as a deployment error rather than anything that
points at the cause:

```
Failed to deploy the test suite: runtime halted: CreateContractSizeLimit (gas_used=1000000000)
```

The contract under test was nowhere near the limit — `contract/` is 20,771
bytes and the library is far smaller. It was purely test data.

**Workaround:** gate large fixtures and their tests with
`#[cfg(target = "native")]`. Native builds are executables with no size limit,
so the data costs nothing there. The MPT verifier is backend-independent, and
what *is* EVM-specific — the Keccak opcode versus the software implementation
— is covered by a test carrying no fixture data.

**Worth reporting upstream**, in two parts. The diagnostic should name the
suite's size and ideally the largest contributors, since
`CreateContractSizeLimit` with no further detail gives a reader nothing to act
on; `--emit sizes` exists for contracts and the same breakdown for a test
suite would have answered it immediately. And test data arguably should not be
subject to a deployment limit at all: a test harness could place large
constants outside the deployed code, or the backend could split a suite across
several contracts.

Not filed yet. Distinct from issue #1951 (no warning when a *contract* exceeds
EIP-170), which was fixed by #1956 — this is about the test suite, and about
the diagnostic rather than the limit.

## `fe fmt` writes array literals one element per line, and compile time grows worse than linearly

Found 2026-11-22 while adding differential trie vectors.

`fe fmt` expands `let bytes: [u8; N] = [0x01, 0x02, ...]` to one element per
line. A 44 KB byte array becomes a 625 KB, 44,569-line source file. That alone
is awkward; the compile time is the real problem.

Measured on the same machine and suite:

| Fixture data in the suite | Source lines | `fe test --backend native` |
| --- | --- | --- |
| the existing fixtures | ~47,000 | **22 s** |
| plus one 44 KB array | ~92,000 | **did not finish in 6 min** |
| plus one 8.6 KB array | ~56,000 | **14 s** |

Roughly doubling the data did not roughly double the time. 8.6 KB is fine and
44 KB is not, so the usable size sits somewhere between, and the growth is
clearly superlinear in a single array literal rather than in total source size.

**Workarounds:** keep any one array literal small, and pack several values into
one blob with an index rather than emitting many functions. The vector count
here was cut from 80 to 28 for this reason and no other.

**Worth reporting upstream** in two parts, as with the test-suite size limit.
`fe fmt` could keep a long numeric array packed several per line, which is what
a human would write and what the generator emitted before formatting. And the
compiler's handling of a large array literal looks like it has an avoidable
superlinear step — a reproduction is trivial to produce (`[u8; N]` for growing
N with a `for` loop over it).

Not filed yet.

## `fe fmt` can wrap a `static_assert` into something `fe check` rejects

Found 2026-11-23 while emitting generated `static_assert`s.

A `static_assert` whose body is long enough to wrap is reformatted by `fe fmt`
with a trailing comma before the closing paren:

```fe
static_assert(
    PAYLOAD_STATE_ROOT_GINDEX
        == payload_field_gindex<Capella>(field: PAYLOAD_STATE_ROOT_FIELD),
)
```

`fe check` then refuses it:

```
error[1-0001]: missing closing `)` for static assertion
    │         == payload_field_gindex<Capella>(PAYLOAD_STATE_ROOT_FIELD),
    │                                                                   ^ expected `)`
```

So the formatter produces source the compiler will not accept, which is worse
than a cosmetic bug: `fe fmt --check` is in CI, so a long assertion cannot be
written in a form that survives both.

**Not yet reduced to a clean minimal repro.** Two attempts did not reproduce
it: a wrapped comparison of two long constant names formats without a trailing
comma and compiles, and so does one calling a plain `const fn`. The real case
has a *generic* call with a labelled argument inside the comparison, and the
difference has not been isolated. The real file is the evidence
(`verife/src/fixture_historical_capella.fe` as generated before the
workaround).

**Workaround in use:** keep every `static_assert` short enough that it never
wraps, by naming the derived side first:

```fe
const DERIVED_STATE_ROOT_GINDEX: u64 =
    payload_field_gindex<Capella>(field: PAYLOAD_STATE_ROOT_FIELD)
static_assert(PAYLOAD_STATE_ROOT_GINDEX == DERIVED_STATE_ROOT_GINDEX)
```

This reads better anyway, so the workaround is not a cost.

Worth reporting once the repro is isolated: either the parser should accept a
trailing comma in a static assertion, or the formatter should not emit one.

Not filed yet.

## `core::hash::sha256_word` is not a `const fn`, which blocks compile-time Merkle constants

Found 2026-11-23 while costing a proof-compression idea.

An SSZ `List[T, N]` is merkleised over its full capacity, so a list with 1,158
entries in a tree of capacity 2^24 has **zero subtrees** above the populated
region. The hashes of those subtrees are pure functions of depth:

```
zero_hash(0) = 0
zero_hash(d) = sha256(zero_hash(d-1) ‖ zero_hash(d-1))
```

Nothing about them depends on runtime data. A proof could therefore omit every
sibling that is a zero-subtree hash and have the verifier reconstruct it —
about 13 of the 24 siblings in a `historical_summaries` branch, roughly 416
bytes off a 2,660-byte call.

The part that would have made it *this project's* kind of idea is that the
table is derivable from the layout type at compile time. It is not:

```fe
const fn zero_hash_one() -> u256 {
    let pair: [u8; 64] = [0; 64]
    sha256_word(pair)        // error[3-0073]
}
```

```
error[3-0073]: non-const function call in const context
   │     sha256_word(pair)
   │     ----------------- calls in const context must be `const fn`
error[8-0062]: non-const call in `const fn`
```

`core::hash::sha256_word` is an ordinary function, so no hash can be folded at
compile time, and the whole family of *derived cryptographic constants* —
zero-subtree tables, precomputed empty roots, domain separators — has to be
hardcoded and then checked by a runtime test instead of being computed and
pinned by `static_assert`.

**Not a bug**, and plausibly deliberate: a const-evaluated SHA-256 means
running the compression function in the compiler. But it is a real limit on
how far "derive it from the type" can be taken, and it is the reason
`hash.fe`'s `EMPTY_TRIE_ROOT` and `KECCAK_EMPTY` are literals with tests
behind them rather than `const fn`s with `static_assert`s.

Worth raising upstream as a question rather than a defect: is `const fn`
hashing intended to be possible, and if so for which primitives? The answer
changes what a library like this can verify at build time.

Not filed yet.
