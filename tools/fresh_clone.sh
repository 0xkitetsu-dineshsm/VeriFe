#!/usr/bin/env bash
# Clone this repository as a judge would, and run its own checks.
#
#     tools/fresh_clone.sh
#
# Everything else in the suite runs against the working tree, where a file can
# be present because it was generated hours ago and never committed. This runs
# against a clone of HEAD in a temporary directory, which is the only way to
# find out whether what is *committed* is what works.
#
# What it would catch, and nothing else does:
#
#   * a generated module that exists on disk but was never `git add`ed
#   * a path that resolves only because of where the script was invoked from
#   * a `.gitignore` entry that excludes something the build needs
#   * a tool the build needs that happens to be installed here
#
# It does not need network access beyond what `./check.sh` itself uses.

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
keep=0
[[ "${1:-}" == "--keep" ]] && keep=1

tmp="$(mktemp -d)"
cleanup() { ((keep)) && echo "clone kept at $tmp" || rm -rf "$tmp"; }
trap cleanup EXIT

echo "VeriFe — a fresh clone of HEAD, checked as a judge would"
echo

printf "  %-42s" "cloning HEAD into a temp directory"
if git -C "$here" clone --quiet --no-hardlinks . "$tmp/verife" 2>/dev/null; then
    echo "ok  $(git -C "$tmp/verife" rev-parse --short HEAD)"
else
    echo "FAIL"; exit 1
fi

cd "$tmp/verife"

# Anything the working tree has that the clone does not is, by definition, not
# committed. Generated Fe modules are the likely casualty.
printf "  %-42s" "files the build needs but HEAD lacks"
missing=0
while IFS= read -r f; do
    [[ -e "$tmp/verife/$f" ]] || { echo; echo "      missing: $f"; missing=$((missing+1)); }
done < <(cd "$here" && ls verife/src/*.fe evm_mpt_tests/src/*.fe contract/src/*.fe \
         reader/src/*.fe cli/src/*.fe integration/*.sol 2>/dev/null)
((missing == 0)) && echo "none" || { echo "      $missing missing"; exit 1; }

printf "  %-42s" "the pinned toolchain is what it says"
v="$(fe --version 2>/dev/null)"
[[ "$v" == *"26.7.0"* ]] && echo "ok  $v" || { echo "FAIL  got '$v'"; exit 1; }

echo
echo "  running ./check.sh inside the clone"
echo "  ------------------------------------------------------------"
if ./check.sh 2>&1 | sed 's/^/  /'; then
    echo "  ------------------------------------------------------------"
    echo
    echo "all good. what is committed is what works."
else
    echo "  ------------------------------------------------------------"
    echo
    echo "FAILED — the clone does not pass its own checks."
    echo "Run with --keep to inspect $tmp."
    exit 1
fi
