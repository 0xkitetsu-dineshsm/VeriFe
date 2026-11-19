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
