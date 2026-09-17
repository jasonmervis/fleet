#!/bin/sh
# Report the live agent fleet. See SPEC.md.
set -eu

. "$(dirname "$0")/lib/common.sh"

usage() {
  cat <<'USAGE'
Usage: status.sh [--workspace <id>] [--dry-run] [--help]

Prints one line per live agent as "<pane_id>  <status>  <cwd>".

Options:
  --workspace <id>  Herdr workspace to query (default: $HERDR_WORKSPACE_ID)
  --dry-run         Print the command that would run; execute nothing
  --help            Print this help and exit 0
USAGE
}

workspace=''
dry_run=0

while [ $# -gt 0 ]; do
  case $1 in
    --help|-h) usage; exit 0 ;;
    --dry-run) dry_run=1 ;;
    --workspace)
      [ $# -ge 2 ] || die "--workspace requires a value"
      workspace=$2
      [ -n "$workspace" ] || die "--workspace requires a non-empty value"
      shift
      ;;
    --workspace=*)
      workspace=${1#--workspace=}
      [ -n "$workspace" ] || die "--workspace requires a non-empty value"
      ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

# Dry-run stays offline: no Herdr, no filesystem, no subprocesses.
if [ "$dry_run" = 1 ]; then
  if [ -n "$workspace" ]; then
    emit 1 herdr agent list --workspace "$workspace"
  else
    emit 1 herdr agent list
  fi
  exit 0
fi

need herdr
need jq
require_herdr
[ -n "$workspace" ] || workspace=$HERDR_WORKSPACE_ID

listing=$(herdr agent list --workspace "$workspace") || die "herdr agent list failed"

# Tolerate either a wrapped ({"result":{"agents":[...]}}) or bare listing; an
# empty fleet yields no lines, which is success, not an error.
printf '%s\n' "$listing" | jq -r '
  (.result.agents? // .agents? // .result? // . // []) as $a
  | (if ($a | type) == "array" then $a else [] end)
  | .[]
  | [ (.pane_id // .pane // "-")
    , (.status  // .state // "-")
    , (.cwd     // .directory // "-")
    ] | join("  ")
'
