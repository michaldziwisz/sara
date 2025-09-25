#!/usr/bin/env bash
set -euo pipefail
WORKFLOW="windows-build.yml"
run_json=$(gh run list --workflow "$WORKFLOW" --limit 1 --json databaseId,status,conclusion)
run_id=$(echo "$run_json" | jq -r '.[0].databaseId // empty')
status=$(echo "$run_json" | jq -r '.[0].status // empty')
conclusion=$(echo "$run_json" | jq -r '.[0].conclusion // empty')
if [[ -z "$run_id" ]]; then
  echo "No runs found for workflow $WORKFLOW" >&2
  exit 1
fi
if [[ "$status" != "completed" || "$conclusion" != "success" ]]; then
  echo "Latest run $run_id is not successful (status=$status, conclusion=$conclusion)" >&2
  exit 1
fi
scripts/download_latest_artifact.sh "$run_id"
