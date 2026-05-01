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
  else
    c_blue "→ coii setup --wizard"
    coii setup --wizard
  fi
}

print_next() {
  c_green "✓ coii installed."
  # Warn if the uv tool bin dir isn't on the user's persistent PATH — without
  # this, `coii` won't be callable in a fresh shell.
  if [ -n "$UV_BIN_DIR" ] && ! printf ':%s:' "$ORIG_PATH" | grep -q ":$UV_BIN_DIR:"; then
    c_yellow ""
    c_yellow "⚠ $UV_BIN_DIR is not on your shell PATH."
    c_yellow "  Add it permanently with:  uv tool update-shell"
    c_yellow "  Or for this session:      export PATH=\"$UV_BIN_DIR:\$PATH\""
  fi
  cat <<'EOF'

Next steps:
  • coii serve              run the FastAPI backend
  • Edit ~/.coii/config.json       global config (LLM provider, runtime defaults)
  • Edit ~/.coii/agents/coder/     identity files (SOUL.md, USER.md, ...)
  • Drop *_workflow.yaml files into ~/.coii/workflows/ to add triggers
  • Set ANTHROPIC_API_KEY (and OPENAI_API_KEY if used) in your shell

To remove later:
  • coii uninstall          delete ~/.coii/ (runtime data + memory)
  • uv tool uninstall coii  remove the CLI binary

Docs: https://github.com/gggh2/coii
EOF
}

require_uv
install_pkg
run_setup
print_next
