# shared test helpers
FAILED=0
check() { # check <desc> <condition-cmd...>
  desc=$1; shift
  if "$@" >/dev/null 2>&1; then printf '  ok   %s\n' "$desc"
  else printf '  FAIL %s\n' "$desc"; FAILED=1; fi
}
contains() { printf '%s' "$1" | grep -q -- "$2"; }
finish() { # finish <name>
  if [ "$FAILED" -eq 0 ]; then printf 'PASS %s\n' "$1"; exit 0
  else printf 'FAIL %s\n' "$1"; exit 1; fi
}
