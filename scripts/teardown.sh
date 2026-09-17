#!/bin/sh
# teardown.sh — remove one worker: close its Herdr tab, then remove its git worktree.
# The branch is never deleted (see ORCHESTRATION.md §8). Contract: SPEC.md.
set -eu

. "$(dirname "$0")/lib/common.sh"

usage() {
  cat <<'EOF'
Usage: teardown.sh --name <name> [--tab <tab_id>] [--force] [--dry-run] [--help]

Closes the worker's tab and removes its worktree at <repo>/.worktrees/<name>.
The branch is left in place.

Options:
  --name <name>   worker name, also the tab label (required)
  --tab <tab_id>  tab to close, e.g. w3:t2; looked up from the label when omitted
  --force         pass --force to git worktree remove (discards uncommitted work)
  --dry-run       print the commands that would run; change nothing
  --help          print this message
EOF
}

name=''
tab=''
force=0
dry=0

while [ $# -gt 0 ]; do
  case $1 in
    --help)    usage; exit 0 ;;
    --name)    [ $# -ge 2 ] || die "--name requires a value"; name=$2; shift 2 ;;
    --tab)     [ $# -ge 2 ] || die "--tab requires a value";  tab=$2;  shift 2 ;;
    --force)   force=1; shift ;;
    --dry-run) dry=1;   shift ;;
    *)         die "unknown option: $1" ;;
  esac
done

[ -n "$name" ] || die "--name is required"
# Names are also path components; anything outside the spawn charset could escape .worktrees/.
case $name in
  [a-z]) ;;
  [a-z]*[!a-z0-9_-]*) die "--name must match [a-z][a-z0-9_-]*: $name" ;;
  [a-z]*) ;;
  *) die "--name must match [a-z][a-z0-9_-]*: $name" ;;
esac

root=$(repo_root)
dir="$root/.worktrees/$name"
# Run git from the repo root so the emitted command is exactly what SPEC.md asks for.
cd "$root"

if [ "$dry" = 1 ]; then
  # Dry-run neither requires Herdr nor resolves the tab, so show the lookup as a command.
  if [ -z "$tab" ]; then
    emit 1 herdr tab list --workspace "${HERDR_WORKSPACE_ID:-<workspace>}"
    tab="<tab_id of label $name>"
  fi
else
  need git
  need herdr
  require_herdr
  if [ -z "$tab" ]; then
    need jq
    tab=$(herdr tab list --workspace "$HERDR_WORKSPACE_ID" \
          | jq -r --arg l "$name" '.result.tabs[]? | select(.label == $l) | .tab_id' \
          | head -n 1)
    [ -n "$tab" ] || die "no tab labelled '$name'; pass --tab <tab_id>"
  fi
fi

emit "$dry" herdr tab close "$tab"

if [ "$force" = 1 ]; then
  emit "$dry" git worktree remove --force "$dir"
else
  emit "$dry" git worktree remove "$dir"
fi
