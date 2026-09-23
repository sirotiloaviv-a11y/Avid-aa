#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed. Download it from https://nodejs.org"
  read -r _
  exit 1
fi
(sleep 1 && open http://localhost:5173) &
node server.mjs src
