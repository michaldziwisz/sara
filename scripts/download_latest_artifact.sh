#!/usr/bin/env bash
set -euo pipefail
RUN_ID="${1?Usage: $0 <run_id>}"
OUT_DIR="artifacts"
ZIP="SARA-windows.zip"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
if ! gh run download "$RUN_ID" --name SARA-windows --dir "$OUT_DIR"; then
  echo "Failed to download artifact for run $RUN_ID" >&2
  exit 1
fi
if [[ ! -f "$OUT_DIR/$ZIP" ]]; then
  echo "Artifact $ZIP not found for run $RUN_ID" >&2
  exit 1
fi
unzip -q "$OUT_DIR/$ZIP" -d "$OUT_DIR/SARA-windows"
