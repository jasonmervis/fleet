#!/bin/sh
# Contract test for scripts/status.sh — see SPEC.md
cd "$(dirname "$0")/.." || exit 1
. tests/lib.sh
S=scripts/status.sh

check "status.sh exists and is executable" test -x "$S"
check "status.sh sources lib/common.sh" grep -q "lib/common.sh" "$S"

HELP=$(sh "$S" --help 2>/dev/null); RC=$?
check "--help exits 0" test "$RC" -eq 0
check "--help prints Usage:" contains "$HELP" "Usage:"

OUT=$(sh "$S" --dry-run 2>/dev/null); RC=$?
check "--dry-run exits 0" test "$RC" -eq 0
check "dry-run mentions herdr agent list" contains "$OUT" "herdr agent list"
finish status
