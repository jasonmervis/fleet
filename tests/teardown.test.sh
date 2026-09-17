#!/bin/sh
# Contract test for scripts/teardown.sh — see SPEC.md
cd "$(dirname "$0")/.." || exit 1
. tests/lib.sh
S=scripts/teardown.sh

check "teardown.sh exists and is executable" test -x "$S"
check "teardown.sh sources lib/common.sh" grep -q "lib/common.sh" "$S"

HELP=$(sh "$S" --help 2>/dev/null); RC=$?
check "--help exits 0" test "$RC" -eq 0
check "--help prints Usage:" contains "$HELP" "Usage:"

sh "$S" --dry-run >/dev/null 2>&1; RC=$?
check "--dry-run without --name exits 2" test "$RC" -eq 2

OUT=$(sh "$S" --name demo --dry-run 2>/dev/null)
check "dry-run mentions herdr tab close"    contains "$OUT" "herdr tab close"
check "dry-run mentions git worktree remove" contains "$OUT" "git worktree remove"
check "dry-run includes the worktree path"  contains "$OUT" ".worktrees/demo"

FOUT=$(sh "$S" --name demo --force --dry-run 2>/dev/null)
check "--force reaches git worktree remove" sh -c 'printf "%s" "$1" | grep "git worktree remove" | grep -q -- "--force"' _ "$FOUT"
finish teardown
