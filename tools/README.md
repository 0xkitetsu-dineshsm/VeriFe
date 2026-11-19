# tools

Supporting tooling. Not Fe, and declared as such in the README: the contest
requires the core technical contribution to be Fe, and this is not part of it.

| Tool | What it does |
| --- | --- |
| `compile_fail.sh` | Runs every `compile_fail/` ingot and requires it to still fail with its recorded diagnostic. `--bless` rewrites the expectations. |

Planned: the proof generator (fetches a finalized `BeaconState`, rebuilds a
period's 8,192 `block_roots`, emits fixtures) and the independent cross-check
against a second SSZ library.
