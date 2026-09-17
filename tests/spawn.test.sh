#!/bin/sh
# Contract test for scripts/spawn.sh — see SPEC.md
cd "$(dirname "$0")/.." || exit 1
. tests/lib.sh
S=scripts/spawn.sh

check "spawn.sh exists and is executable" test -x "$S"
check "spawn.sh sources lib/common.sh" grep -q "lib/common.sh" "$S"

HELP=$(sh "$S" --help 2>/dev/null); RC=$?
check "--help exits 0" test "$RC" -eq 0
check "--help prints Usage:" contains "$HELP" "Usage:"

sh "$S" --dry-run >/dev/null 2>&1; RC=$?
check "--dry-run without --name exits 2" test "$RC" -eq 2
ERR=$(sh "$S" --branch feat/x --dry-run 2>&1 >/dev/null)
check "missing --name names the option on stderr" contains "$ERR" "name"

OUT=$(sh "$S" --name demo --branch feat/demo --dry-run 2>/dev/null)
check "dry-run mentions git worktree add" contains "$OUT" "git worktree add"
check "dry-run includes the worktree path"  contains "$OUT" ".worktrees/demo"
check "dry-run includes the branch"         contains "$OUT" "feat/demo"
check "dry-run mentions herdr tab create"   contains "$OUT" "herdr tab create"
check "dry-run passes --cwd"                contains "$OUT" "--cwd"
check "dry-run passes --label"              contains "$OUT" "demo"
check "dry-run mentions herdr agent start"  contains "$OUT" "herdr agent start"
check "dry-run selects the claude kind"     contains "$OUT" "--kind claude"
check "dry-run created nothing"             test ! -d .worktrees/demo
finish spawn
