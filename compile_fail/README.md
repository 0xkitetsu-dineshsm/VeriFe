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

| Case | The mistake |
| --- | --- |
| `field_past_end` | A field position past the end of its container. |

Planned: a gindex from the wrong fork's layout, segments joined out of
order, and a proof type handed to the wrong verifier.
