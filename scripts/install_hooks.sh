#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
mkdir -p "$HOOKS_DIR"
for hook in post-checkout post-merge; do
  src="$REPO_ROOT/scripts/hooks/$hook"
  dest="$HOOKS_DIR/$hook"
  if [[ -f "$src" ]]; then
    ln -sf "$src" "$dest"
    chmod +x "$dest"
    echo "Installed $hook hook."
  fi
done
