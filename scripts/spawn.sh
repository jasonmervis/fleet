#!/bin/sh
# spawn.sh — create one worker: git worktree + Herdr tab + Claude agent. See SPEC.md.
set -eu

. "$(dirname "$0")/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: spawn.sh --name <name> --branch <branch> [--base <ref>] [--dry-run] [--help]

Creates a worktree at <repo>/.worktrees/<name> on <branch> cut from <ref>, a Herdr tab
rooted in that worktree, and a Claude agent on the tab's root pane.

Options:
  --name <name>      worker name, also the tab label; [a-z][a-z0-9_-]{0,31}  (required)
  --branch <branch>  branch created for the worktree                        (required)
  --base <ref>       ref the branch is cut from (default: main)
  --dry-run          print the commands that would run, change nothing
  --help             print this message
EOF
}

NAME=''
BRANCH=''
BASE=main
DRY=0

while [ $# -gt 0 ]; do
  case $1 in
    --help|-h) usage; exit 0 ;;
    --dry-run) DRY=1; shift ;;
    --name)   [ $# -ge 2 ] || die "missing value for --name";   NAME=$2;   shift 2 ;;
    --branch) [ $# -ge 2 ] || die "missing value for --branch"; BRANCH=$2; shift 2 ;;
    --base)   [ $# -ge 2 ] || die "missing value for --base";   BASE=$2;   shift 2 ;;
    *) die "unknown option: $1" ;;
  esac
done

[ -n "$NAME" ]   || die "missing required option: --name"
[ -n "$BRANCH" ] || die "missing required option: --branch"
[ -n "$BASE" ]   || die "missing value for --base"

# The name becomes a path element and a tab label, so keep it boring.
printf '%s' "$NAME" | grep -q '^[a-z][a-z0-9_-]\{0,31\}$' ||
  die "invalid value for --name: $NAME"

ROOT=$(repo_root)
DIR="$ROOT/.worktrees/$NAME"

# Dry-run stays read-only: no Herdr, no filesystem changes, IDs shown as placeholders
# because the real tab and pane IDs only exist once `herdr tab create` has run.
if [ "$DRY" = 1 ]; then
  emit 1 git worktree add "$DIR" -b "$BRANCH" "$BASE"
  emit 1 herdr tab create --workspace "${HERDR_WORKSPACE_ID:-<workspace_id>}" \
    --cwd "$DIR" --label "$NAME" --no-focus
  emit 1 herdr agent start "$NAME" --kind claude --pane '<pane_id>' -- \
    --permission-mode auto --model opus
  exit 0
fi

need git
need herdr
need jq
require_herdr

if [ -e "$DIR" ]; then
  die "worktree path already exists: $DIR"
fi

cd "$ROOT"
git worktree add "$DIR" -b "$BRANCH" "$BASE"

TAB_JSON=$(herdr tab create \
             --workspace "$HERDR_WORKSPACE_ID" \
             --cwd "$DIR" \
             --label "$NAME" \
             --no-focus) || die "herdr tab create failed for $NAME"

TAB=$(printf '%s' "$TAB_JSON" | jq -r '.result.tab.tab_id')
PANE=$(printf '%s' "$TAB_JSON" | jq -r '.result.root_pane.pane_id')
[ -n "$PANE" ] && [ "$PANE" != null ] || die "no pane_id in herdr tab create output for $NAME"

herdr agent start "$NAME" --kind claude --pane "$PANE" -- \
  --permission-mode auto --model opus

log "spawned $NAME on $BRANCH (base $BASE)"
printf '%s  %s  %s  %s\n' "$NAME" "$TAB" "$PANE" "$DIR"
