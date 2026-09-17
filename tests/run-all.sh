#!/bin/sh
# Run every contract test. Exits non-zero if any fails.
cd "$(dirname "$0")/.." || exit 1
rc=0
for t in tests/*.test.sh; do
  printf '\n== %s ==\n' "$t"
  sh "$t" || rc=1
done
printf '\n'
[ "$rc" -eq 0 ] && printf 'ALL TESTS PASS\n' || printf 'SOME TESTS FAILED\n'
exit "$rc"
