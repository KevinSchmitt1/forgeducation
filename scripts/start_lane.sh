#!/usr/bin/env bash
# Start (or resume) a lane in parallel: a worktree under .worktrees/, then a Claude session in its
# own tmux window whose first move is the CP0 kickoff checkpoint (CLAUDE.md → "Human checkpoints").
#
#   scripts/start_lane.sh 11            # create/resume lane 11 and open tmux window "lane11"
#   scripts/start_lane.sh 11 --dry-run  # print what it would do
#
# The branch comes from the brief's "**Branch:** `...`" line (docs/lanes/NN-*.md).
set -euo pipefail

lane="${1:?usage: scripts/start_lane.sh <NN> [--dry-run]}"
dry_run="${2:-}"

common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
root="${common_dir%/.git}"

shopt -s nullglob
briefs=("$root"/docs/lanes/"$lane"-*.md)
if [[ ${#briefs[@]} -ne 1 ]]; then
  echo "start_lane: expected exactly one docs/lanes/$lane-*.md, found ${#briefs[@]}" >&2
  exit 2
fi
brief_file="$(basename "${briefs[0]}")"
branch="$(sed -n 's/^\*\*Branch:\*\* `\([^`]*\)`.*/\1/p' "${briefs[0]}" | head -1)"
if [[ -z "$branch" ]]; then
  echo "start_lane: no **Branch:** \`...\` line in $brief_file" >&2
  exit 2
fi
slug="lane${lane}-${brief_file#"$lane"-}"
worktree="$root/.worktrees/${slug%.md}"
window="lane${lane}"
prompt="Continue lane ${lane} per docs/lanes/${brief_file}. Follow CLAUDE.md, section Human checkpoints: begin at CP0 - read, then post your kickoff packet with scripts/checkpoint.py and wait for my go before writing any code."

if [[ -d "$worktree" ]]; then
  add_cmd=(true)
  action="resume existing worktree"
elif git -C "$root" show-ref --verify --quiet "refs/heads/$branch"; then
  add_cmd=(git -C "$root" worktree add "$worktree" "$branch")
  action="add worktree for existing branch $branch"
else
  add_cmd=(git -C "$root" worktree add -b "$branch" "$worktree" master)
  action="add worktree + new branch $branch from master"
fi
tmux_cmd=(tmux new-window -d -n "$window" -c "$worktree" claude "$prompt")

echo "lane $lane: $brief_file"
echo "  $action -> $worktree"
echo "  tmux window: $window"
if [[ "$dry_run" == "--dry-run" ]]; then
  echo "  (dry run) ${add_cmd[*]}"
  echo "  (dry run) ${tmux_cmd[*]}"
  exit 0
fi
if [[ -z "${TMUX:-}" ]]; then
  echo "start_lane: not inside tmux — start tmux first so the lane gets its own window" >&2
  exit 2
fi
"${add_cmd[@]}"
"${tmux_cmd[@]}"
echo "  started. Watch the inbox: python scripts/checkpoint.py list"
