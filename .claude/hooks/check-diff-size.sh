#!/usr/bin/env bash
# Pushes back when the working diff grows past what a reviewer can hold in their
# head. This is the friction a human feels naturally and a model does not: every
# extra line costs a person time, and costs the model nothing.
#
# Counts untracked files too — a pile of brand-new files is the usual way a
# change gets out of hand, and plain `git diff` does not see them.
#
# Wired as a PostToolUse hook on Write|Edit. Output is fed back to Claude.

set -uo pipefail

LIMIT=150

changed=$(git diff --numstat HEAD 2>/dev/null | awk '{s+=$1} END {print s+0}')
changed_files=$(git diff --name-only HEAD 2>/dev/null | wc -l | tr -d ' ')

new=$(git ls-files --others --exclude-standard -z 2>/dev/null \
      | xargs -0 -r cat 2>/dev/null | wc -l | tr -d ' ')
new_files=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')

added=$(( ${changed:-0} + ${new:-0} ))
files=$(( ${changed_files:-0} + ${new_files:-0} ))

if [ "$added" -gt "$LIMIT" ]; then
  echo "Diff is now +${added} lines across ${files} files (${new_files} of them new), past the ${LIMIT}-line bar in CLAUDE.md. Stop adding. Either cut what is not strictly required, or check with the user before going further."
fi
