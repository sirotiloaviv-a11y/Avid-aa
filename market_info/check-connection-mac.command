#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed. Download it from https://nodejs.org"
  read -r _
  exit 1
fi
node scripts/check-connection.mjs
open -e connection-report.txt 2>/dev/null
echo
echo "Press Enter to close."
read -r _
