#!/usr/bin/env bash
# coii installer — one-liner entry for the Personal Agent Workforce.
#
#   curl -fsSL https://raw.githubusercontent.com/gggh2/coii/main/install.sh | bash
#
# Steps:
#   1. Install `uv` if missing (asks first when running interactively).
#   2. `uv tool install` coii from this repo's GitHub subdirectory.
#   3. `coii setup --wizard` — interactive provider/Linear/log-level config,
#      then seeds ~/.coii/ with default agents + workflows.
#
# Override the source ref via env vars:
#   COII_REPO=https://github.com/gggh2/coii.git
#   COII_REF=main
#   COII_SUBDIR=backend
#
# Run the wizard non-interactively (for CI / e2e):
#   COII_NONINTERACTIVE=1   plus the wizard's own env inputs
#                           (COII_WIZARD_PROVIDER, COII_WIZARD_API_KEY,
#                            LINEAR_API_KEY, LINEAR_TEAM_KEY, ...). See
#                           `coii setup --wizard --help` for the full list.

set -euo pipefail

REPO="${COII_REPO:-https://github.com/gggh2/coii.git}"
REF="${COII_REF:-main}"
SUBDIR="${COII_SUBDIR:-backend}"

# Snapshot the user's incoming PATH so we can detect at the end whether the
# uv tool bin dir is on their persistent shell PATH or only on our augmented
# in-script PATH.
ORIG_PATH="$PATH"
# Make sure uv's standard install location is reachable for this session.
# (uv installer puts binaries under $HOME/.local/bin or $HOME/.cargo/bin.)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
UV_BIN_DIR=""

c_blue() { printf '\033[34m%s\033[0m\n' "$*"; }
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_red() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

require_uv() {
  if command -v uv >/dev/null 2>&1; then
    c_blue "→ uv already installed ($(uv --version))"
    return
  fi
  c_blue "→ uv not found, installing via astral.sh installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  command -v uv >/dev/null 2>&1 || {
    c_red "uv install failed — check the astral.sh installer output above"
    exit 1
  }
}

install_pkg() {
  local spec
  if [[ "$REPO" == /* ]]; then
    # Local-path install — points at the working tree, not a git ref.
    # Used by the e2e to test install.sh without committing first.
    spec="${REPO}/${SUBDIR}"
  else
    spec="git+${REPO}@${REF}#subdirectory=${SUBDIR}"
  fi
  c_blue "→ uv tool install ${spec}"
  uv tool install --force "$spec"
  # Prepend uv's tool bin dir so `coii` is callable in this session even if
  # the user's shell rc doesn't have it yet. uv prints this dir as a warning
  # when it isn't on PATH; we also tell the user how to make it permanent.
  UV_BIN_DIR="$(uv tool dir --bin 2>/dev/null || true)"
  if [ -n "$UV_BIN_DIR" ]; then
    export PATH="$UV_BIN_DIR:$PATH"
  fi
}

run_setup() {
  if [ "${COII_NONINTERACTIVE:-}" = "1" ]; then
    c_blue "→ coii setup --wizard --non-interactive"
    coii setup --wizard --non-interactive
    return
  fi
  c_blue "→ coii setup --wizard"
  # When run via `curl … | bash`, this script's stdin is the pipe from curl,
  # not the terminal — so the wizard's input() calls would EOF immediately.
  # Redirect stdin from /dev/tty so prompts work. Fall back to inherited
  # stdin if no tty is available (rare; the wizard will fail loudly).
  if [ -r /dev/tty ]; then
    coii setup --wizard </dev/tty
  else
    coii setup --wizard
  fi
}

ensure_path() {
  # If the uv tool bin dir isn't on the user's persistent shell PATH, run
  # `uv tool update-shell` so future shells pick it up. The user still has
  # to source their shell rc (or open a new terminal); we tell them how.
  [ -z "$UV_BIN_DIR" ] && return
  if printf ':%s:' "$ORIG_PATH" | grep -q ":$UV_BIN_DIR:"; then
    return
  fi
  c_blue "→ uv tool update-shell  (adding $UV_BIN_DIR to your shell rc)"
  if uv tool update-shell >/dev/null 2>&1; then
    c_green "  added — open a new terminal, or run:  source your shell rc"
  else
    c_yellow "  could not auto-update shell rc; add this line yourself:"
    c_yellow "    export PATH=\"$UV_BIN_DIR:\$PATH\""
  fi
}

print_next() {
  c_green "✓ coii installed."
  cat <<'EOF'

Next steps:
  • coii serve                  run the FastAPI backend (default :3001)
  • Create a Linear ticket with the `agent:coder` label to trigger your
    first agent run. The poller picks it up on the next interval.

To remove later:
  • coii uninstall              delete ~/.coii/ AND the CLI binary

Docs: https://github.com/gggh2/coii
EOF
}

require_uv
install_pkg
run_setup
ensure_path
print_next
