#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/RedBoy-011/RedSocKs5-NordVPN.git"
BASE_DIR="/opt/RedSocKs5-NordVPN"

if [[ "${EUID}" -ne 0 ]]; then
  echo 'Run with sudo: curl -fsSL https://raw.githubusercontent.com/RedBoy-011/RedSocKs5-NordVPN/main/install.sh | sudo bash'
  exit 1
fi

apt-get update -y
apt-get install -y git ca-certificates curl

if [[ -d "$BASE_DIR/.git" ]]; then
  cd "$BASE_DIR"
  if [[ -n "$(git status --porcelain 2>/dev/null | grep -v '^?? ' || true)" ]]; then
    # Keep untracked private files such as .env on the server.
    git stash push -m "RedSocKs5 automatic backup $(date +%Y%m%d-%H%M%S)" || true
  fi
  git pull --ff-only origin main
else
  mkdir -p "$(dirname "$BASE_DIR")"
  git clone "$REPO_URL" "$BASE_DIR"
  cd "$BASE_DIR"
fi

chmod +x RedSocKs5
# The installer may itself be run through curl|bash. Force the interactive
# menu to read from the terminal instead of the exhausted download pipe.
if [[ -r /dev/tty ]]; then
  exec ./RedSocKs5 </dev/tty
else
  exec ./RedSocKs5
fi
