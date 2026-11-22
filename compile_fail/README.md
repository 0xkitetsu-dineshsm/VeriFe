# compile_fail

Each directory here is an ingot that **must not compile**. Every case pairs a
mistake a verifier author could plausibly make with the diagnostic Fe produces
for it, recorded verbatim in `expected.txt`.

These are the Fe-specific part of VeriFe's safety argument: the equivalent
Solidity libraries (Lido's `GIndex`, EigenLayer's `BeaconChainProofs`) can only
catch these at run time, if at all.

`tools/compile_fail.sh` runs every case and fails if one of them compiles, or
if its diagnostic no longer matches `expected.txt`.

This directory is listed in `[workspace].exclude`, so `fe build` and `fe test`
at the repo root never try to compile it.

| Case | The mistake | What Fe says |
| --- | --- | --- |
| `field_past_end` | A field position past the end of its container. | `field index past the end of the container` |
| `segments_out_of_order` | Two path segments spliced the wrong way round. | `left: 457` / `right: 412` |
| `wrong_fork_gindex` | A Capella layout checked against Electra's `block_roots` gindex. | `left: 37` / `right: 69` |
| `wrong_fork_proof` | A proof built for one fork handed to another fork's verifier. | ``expected `RecentProof<Fulu>`, but `RecentProof<Capella>` is given`` |
| `wrong_proof_length` | A branch of the wrong depth for its fork (invariant 6). | ``expected `[u256; 18]`, but `[u256; 19]` is given`` |
| `undeclared_anchor_effect` | Reading an anchor root without declaring the effect it needs. | ``missing effect row `S::E` required by `root_at`` |

`wrong_fork_proof` and `wrong_proof_length` are the ones worth reading the
sources for. Neither mentions a
number: `RecentProof<L>` sizes its branch with
`block_root_proof_len<L>()`, a `const fn` of the fork's field count, so the
`18` in that diagnostic was derived by the compiler from `Capella` and never
written by anyone. A library where a proof is `bytes32[]` cannot produce
either error -- both mistakes compile, and are caught at run time if they are
caught at all.

`undeclared_anchor_effect` is a different kind of claim: not a wrong number or
a wrong shape, but a signature that hides what it does. `AnchorSource` carries
an associated effect row (`uses E`), bound to the EVM `Call` effect by the
EIP-4788 implementation and to nothing by the fixture one. A wrapper that reads
a root without forwarding that row does not compile, so "fetch the anchor root"
cannot be made to look like a getter. That is the compile-time half of
invariant 1.

Checked the way the Fe tests are: making `wrong_fork_gindex` correct (`== 37`)
makes the suite report `FAIL wrong_fork_gindex: it compiled, and it must not`
and exit 1, so these cases fail when they stop failing.
