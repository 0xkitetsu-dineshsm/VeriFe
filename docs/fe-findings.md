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
