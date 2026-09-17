#!/bin/sh
# Report the live agent fleet. See SPEC.md.
set -eu

. "$(dirname "$0")/lib/common.sh"

usage() {
  cat <<'USAGE'
Usage: status.sh [--workspace <id>] [--dry-run] [--help]

Prints one line per live agent as "<pane_id>  <status>  <cwd>".

Options:
  --workspace <id>  Only report agents in this workspace (default: $HERDR_WORKSPACE_ID)
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

# `herdr agent list` takes no options, so --workspace is a client-side filter on
# each agent's workspace_id — the dry-run line shows the command as actually run.
if [ "$dry_run" = 1 ]; then
  emit 1 herdr agent list
  exit 0
fi

need herdr
need jq
require_herdr
[ -n "$workspace" ] || workspace=$HERDR_WORKSPACE_ID

listing=$(herdr agent list) || die "herdr agent list failed"

# An empty fleet yields no lines, which is success, not an error.
printf '%s\n' "$listing" | jq -r --arg ws "$workspace" '
  (.result.agents // [])
  | map(select(.workspace_id == $ws))
  | .[]
  | [ (.pane_id // "-")
    , (.agent_status // "-")
    , (.cwd // "-")
    ] | join("  ")
'
