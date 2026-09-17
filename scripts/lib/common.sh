# Shared helpers for the fleet scripts. Source, do not execute.
# shellcheck shell=sh

log()  { printf '%s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 2; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1"; }

repo_root() { git rev-parse --show-toplevel 2>/dev/null || die "not a git repository"; }

require_herdr() {
  [ "${HERDR_ENV:-}" = "1" ] || die "not running inside Herdr"
  [ -n "${HERDR_WORKSPACE_ID:-}" ] || die "HERDR_WORKSPACE_ID is unset"
}

# emit <dry_run> <command...> : run it, or print it when dry_run is 1
emit() {
  _dry=$1; shift
  if [ "$_dry" = "1" ]; then printf '%s\n' "$*"; else "$@"; fi
}
