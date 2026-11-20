#!/usr/bin/env bash
# Run every ingot under compile_fail/ and require that each one still fails to
# compile with the diagnostic recorded next to it.
#
#   tools/compile_fail.sh           check every case
#   tools/compile_fail.sh --bless   rewrite every expected.txt from the compiler
#
# Line and column numbers are normalized away before comparing, so that moving
# a function inside verife/ does not churn these files; everything else -- the
# error codes, the spans, the messages -- must match exactly.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bless=0
[[ "${1:-}" == "--bless" ]] && bless=1

normalize() {
    # Drop line numbers -- in the gutter (including the multi-line `\u2502 \u256d`
    # and `\u2502 \u2502` forms) and in `path:line:col` references -- plus
    # trailing whitespace and trailing blank lines. Everything else (the error
    # codes, the spans, the messages, the `left:`/`right:` values) must match
    # exactly. This keeps a case from churning when an unrelated edit moves a
    # function inside verife/.
    sed -E -e 's/^ *[0-9]+ (\xe2\x94\x82)/ \1/' \
           -e 's/^( *\xe2\x94\x8c\xe2\x94\x80 [^:]+):[0-9]+:[0-9]+/\1/' \
           -e 's/[[:space:]]+$//' |
        awk 'NF {for (i = 0; i < blanks; i++) print ""; blanks = 0; print; next}
             {blanks++}'
}

status=0
for case_dir in "$root"/compile_fail/*/; do
    [[ -f "$case_dir/fe.toml" ]] || continue
    name="$(basename "$case_dir")"
    actual="$(fe check --color never "$case_dir" 2>&1)" && {
        echo "FAIL $name: it compiled, and it must not"
        status=1
        continue
    }
    if (( bless )); then
        printf '%s\n' "$actual" > "$case_dir/expected.txt"
        echo "BLESS $name"
        continue
    fi
    if diff -u \
        <(normalize < "$case_dir/expected.txt") \
        <(printf '%s\n' "$actual" | normalize) > /tmp/compile_fail_diff.$$ 2>&1
    then
        echo "ok   $name"
    else
        echo "FAIL $name: the diagnostic changed"
        cat /tmp/compile_fail_diff.$$
        status=1
    fi
    rm -f /tmp/compile_fail_diff.$$
done

exit $status
