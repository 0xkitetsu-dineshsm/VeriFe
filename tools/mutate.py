"""Delete each guard in turn and see whether any test notices.

A guard no test notices is not necessarily a bug -- it can be genuine defence
in depth, where violating it is unreachable for another reason. But it is
*not tested*, and the difference between those two things is exactly what a
comment claiming "this is checked" hides.
"""
import atexit, re, subprocess, sys, shutil
from pathlib import Path

src = Path(sys.argv[1])
original = src.read_text()

# Interrupting this script between mutants would otherwise leave a guard
# deleted in the working tree -- which has happened, and which the next
# commit would have carried.
atexit.register(lambda: src.write_text(original))
lines = original.splitlines(keepends=True)

# Only guards before the first test, i.e. library code rather than assertions
# inside tests (where deleting one trivially changes nothing).
first_test = next(i for i, l in enumerate(lines) if l.startswith("#[test")
                  or l.startswith('#[cfg(target = "native")]\n') and i+1 < len(lines) and lines[i+1].startswith("#[test"))
for i, l in enumerate(lines):
    if l.lstrip().startswith("#[test"):
        first_test = i
        break

def span_of_assert(start: int):
    """Line range [start, end] of a possibly multi-line assert!(...)."""
    depth = 0
    for n in range(start, len(lines)):
        depth += lines[n].count("(") - lines[n].count(")")
        if depth <= 0:
            return n
    return start

targets = []
n = 0
while n < first_test:
    if re.match(r"\s*assert!\(", lines[n]):
        end = span_of_assert(n)
        targets.append((n, end))
        n = end + 1
    else:
        n += 1

print(f"{src.name}: {len(targets)} guards before the first test", flush=True)
unnoticed = []
for k, (a, b) in enumerate(targets):
    label = lines[a].strip()[:68]
    mutated = lines[:a] + lines[b+1:]
    src.write_text("".join(mutated))
    r = subprocess.run(["fe", "test", "--backend", "native", "-i", "verife"],
                       capture_output=True, text=True)
    noticed = "FAILED" in r.stdout or "Compilation errors" in r.stdout or r.returncode != 0
    why = "noticed" if noticed else "** NOT NOTICED **"
    if "Compilation errors" in r.stdout:
        why = "noticed (does not compile without it)"
    print(f"  [{k+1:2}/{len(targets)}] line {a+1:4}  {why:38}  {label}", flush=True)
    if not noticed:
        unnoticed.append((a+1, label))
    src.write_text(original)

print()
print(f"=== {len(unnoticed)} of {len(targets)} guards are not noticed by any test ===")
for ln, lbl in unnoticed:
    print(f"  line {ln}: {lbl}")
