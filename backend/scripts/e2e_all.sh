#!/usr/bin/env bash
# Run every e2e suite (excluding webhook). Sequential because they share
# global state (~/.coii backups, Linear API quota).
#
#   ./scripts/e2e_all.sh
#
# Includes:
#   - e2e_install.sh   local-only: install / config CLI / serve / uninstall
#   - e2e_polling.py   live Linear: ticket.created / updated / commented
#   - e2e_dispatch.py  full pipeline: poll → dispatch → LLM → comment posted
#                      (skips cleanly if no working LLM key in .env.test)
#
# Webhook coverage (e2e_demo.py) is *not* run here — it requires a public
# tunnel (Cloudflare / ngrok) and an already-running backend. Run it
# manually after pointing Linear at your tunnel URL.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"

step()  { printf '\n\033[1;36m▶▶▶ %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m=== %s ===\033[0m\n' "$*"; }
fail()  { printf '\033[1;31m=== %s ===\033[0m\n' "$*" >&2; exit 1; }

cd "$BACKEND"

step "1/3  e2e_install.sh — local install + config + serve"
bash "$HERE/e2e_install.sh" || fail "e2e_install FAILED"
ok "e2e_install PASSED"

step "2/3  e2e_polling.py — live Linear poll + dispatch integration"
uv run python "$HERE/e2e_polling.py" || fail "e2e_polling FAILED"
ok "e2e_polling PASSED"

step "3/3  e2e_dispatch.py — full pipeline with LLM"
uv run python "$HERE/e2e_dispatch.py" || fail "e2e_dispatch FAILED"
ok "e2e_dispatch PASSED (or skipped — see output)"

printf '\n\033[1;32m✓ ALL E2E PASSED\033[0m\n'
