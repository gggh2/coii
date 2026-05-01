#!/usr/bin/env bash
# End-to-end smoke test for the local install / config / serve / uninstall
# lifecycle. NO Linear API calls — every scenario here is local-only.
#
# Backs up the live ~/.coii/ before doing anything destructive; restores it
# at the end (or on any failure via the EXIT trap).
#
# What it covers (in order):
#   1. Pre-state clean (~/.coii absent, no `coii` binary on PATH)
#   2. `uv tool install` from the local checkout
#   3. `coii version`
#   4. `coii init` seeds ~/.coii/{config.json, agents/coder/*, workflows/*}
#   5. `coii setup` (no flag) is an idempotent re-init
#   6. `coii config` CLI: file/get/set/unset/validate/audit + SecretRef builder
#   7. Polling auto-registers when trackers.linear.team_keys is set in JSON
#      (verified via /cron/status; the new bug-fix path)
#   8. `coii serve` boots; /health, /cron/status, POST /cron/run/{name}
#   9. `coii uninstall --yes`  (also removes the CLI binary by default)
#  10. Confirm binary is gone
#  11. Final state fully clean
#
# Live Linear coverage lives in ./scripts/e2e_polling.py and ./scripts/e2e_demo.py.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG_DIR="$REPO_ROOT/backend"
ENV_FILE="$REPO_ROOT/.env.local_deploy"
BACKUP="/tmp/coii_e2e_backup_$$"
SERVE_PORT=3099
SERVE_LOG="/tmp/coii_e2e_serve_$$.log"
SERVE_PID=""

ok()    { printf '\033[32m✓\033[0m %s\n' "$*"; }
fail()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
step()  { printf '\n\033[34m── %s\033[0m\n' "$*"; }

cleanup() {
  set +e
  [ -n "$SERVE_PID" ] && kill "$SERVE_PID" 2>/dev/null
  uv tool uninstall coii 2>/dev/null
  rm -rf ~/.coii
  if [ -d "$BACKUP" ]; then
    mv "$BACKUP" ~/.coii
    echo "  restored ~/.coii from $BACKUP"
  fi
}
trap cleanup EXIT

# Helper: assert a path matches an expected literal value via `coii config get`.
# usage: assert_get <path> <expected>
assert_get() {
  local p="$1"; local want="$2"
  local got; got="$(coii config get "$p" 2>/dev/null || true)"
  [ "$got" = "$want" ] || fail "config get $p: want $want got $got"
}

# Helper: assert `coii config audit` exits with the expected code, optionally
# matching a substring in stdout.
# usage: assert_audit_exit <expected-rc> [<must-contain>]
assert_audit_exit() {
  local want="$1"; local needle="${2:-}"
  local out; local got
  out="$(coii config audit 2>&1 || true)"
  got=$?
  # bash assigns `$?` to whatever the *last* command returned; capture via $PIPESTATUS instead.
  # We re-run with a captured exit to be safe:
  set +e
  out="$(coii config audit 2>&1)"
  got=$?
  set -e
  [ "$got" = "$want" ] || { echo "$out" >&2; fail "config audit: want exit $want, got $got"; }
  if [ -n "$needle" ]; then
    echo "$out" | grep -q "$needle" || fail "audit output missing '$needle'"
  fi
}

# ── 0. backup
step "Backup live ~/.coii → $BACKUP"
if [ -e ~/.coii ]; then
  mv ~/.coii "$BACKUP"
  ok "backed up"
else
  ok "(no live ~/.coii to back up)"
fi

# ── 1. pre-state
step "Pre-install state checks"
[ ! -e ~/.coii ] || fail "~/.coii unexpectedly exists"
ok "~/.coii absent"
if command -v coii >/dev/null 2>&1; then
  fail "coii is already on PATH (uninstall it first: uv tool uninstall coii)"
fi
ok "coii binary not on PATH"

# ── 2. install
step "uv tool install $PKG_DIR"
# Bust the wheel cache so a freshly-edited PKG_DIR rebuilds. `--force` only
# re-installs; it doesn't invalidate uv's hash-of-source-tree cache, so
# without this an iteration of "edit code → rerun e2e" silently runs the
# previous binary.
uv cache clean coii >/dev/null 2>&1 || true
uv tool install --force "$PKG_DIR" >/dev/null
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
command -v coii >/dev/null 2>&1 || fail "coii missing from PATH after install"
ok "coii on PATH: $(command -v coii)"

# ── 3. version
step "coii version"
ver=$(coii version)
[ -n "$ver" ] || fail "coii version produced no output"
ok "version: $ver"

# ── 4. init
step "coii init"
coii init
[ -f ~/.coii/config.json ] || fail "config.json not seeded"
[ -f ~/.coii/agents/coder/SOUL.md ] || fail "agents/coder/SOUL.md not seeded"
[ -f ~/.coii/agents/coder/IDENTITY.md ] || fail "agents/coder/IDENTITY.md not seeded"
[ -f ~/.coii/workflows/default_coder_linear_workflow.yaml ] || fail "workflow yaml not seeded"
ok "seeded: config.json + agents/coder/* + workflows/*"

# Snapshot the freshly-seeded config.json so later mutations can't pollute the
# init-vs-setup-idempotency check.
INIT_HASH="$(shasum ~/.coii/config.json | awk '{print $1}')"

# ── 5. `coii setup` (no flag) is idempotent re-init
step "coii setup (no flags) — idempotent re-init"
out=$(coii setup)
echo "$out" | grep -q "seeded" || fail "coii setup did not print seed summary"
[ "$(shasum ~/.coii/config.json | awk '{print $1}')" = "$INIT_HASH" ] || \
  fail "coii setup overwrote a user file (config.json hash changed)"
ok "coii setup ≡ coii init (no overwrites)"

# ── 5z. `install.sh` end-to-end with COII_NONINTERACTIVE=1
# Drives the curl|bash code path against a local git URL so we don't hit
# GitHub. Verifies: install.sh runs uv tool install + the non-interactive
# wizard, leaving ~/.coii populated and coii still on PATH.
step "install.sh (curl|bash flow) — local file://, non-interactive"
INSTALL_SH="$REPO_ROOT/install.sh"
[ -x "$INSTALL_SH" ] || { chmod +x "$INSTALL_SH" 2>/dev/null || true; }
# Tear down so install.sh exercises the full install path.
uv tool uninstall coii >/dev/null 2>&1 || true
rm -rf ~/.coii
uv cache clean coii >/dev/null 2>&1 || true
# Drive the bundled installer against the local checkout. We pass a plain
# absolute path (not git+file://) so install.sh installs the *working tree*,
# letting us validate uncommitted changes before pushing.
INSTALL_LOG="/tmp/coii_install_sh_$$.log"
COII_REPO="$REPO_ROOT" \
  COII_NONINTERACTIVE=1 \
  COII_WIZARD_PROVIDER=anthropic \
  COII_WIZARD_API_KEY=fake-anthropic-key \
  COII_WIZARD_MODEL=anthropic/claude-haiku-4-5-20251001 \
  COII_WIZARD_LOG_LEVEL=info \
  LINEAR_API_KEY=fake-linear-key \
  LINEAR_TEAM_KEY=LEL \
  LINEAR_WEBHOOK_SECRET=fake-webhook-secret \
  bash "$INSTALL_SH" >"$INSTALL_LOG" 2>&1 \
    || { tail -50 "$INSTALL_LOG"; fail "install.sh exited non-zero"; }
command -v coii >/dev/null 2>&1 || fail "coii not on PATH after install.sh"
[ -f ~/.coii/config.json ] || fail "~/.coii/config.json missing after install.sh"
[ "$(coii config get models.default)" = "anthropic/claude-haiku-4-5-20251001" ] \
  || fail "install.sh wizard didn't write model spec"
ok "install.sh installed coii + ran wizard --non-interactive end-to-end"
rm -f "$INSTALL_LOG"

# ── 5a. `coii setup --wizard --non-interactive` end-to-end
step "coii setup --wizard --non-interactive (driven by env vars)"
# Reset to a fresh ~/.coii so the wizard writes a known shape.
rm -rf ~/.coii
WIZARD_LOG="/tmp/coii_wizard_$$.log"
COII_WIZARD_PROVIDER=anthropic \
  COII_WIZARD_API_KEY=fake-anthropic-key \
  COII_WIZARD_MODEL=anthropic/claude-haiku-4-5-20251001 \
  COII_WIZARD_LOG_LEVEL=warning \
  LINEAR_API_KEY=fake-linear-key \
  LINEAR_TEAM_KEY=LEL \
  LINEAR_WEBHOOK_SECRET=fake-webhook-secret-from-env \
  coii setup --wizard --non-interactive >"$WIZARD_LOG" 2>&1 \
    || { tail -40 "$WIZARD_LOG"; fail "wizard --non-interactive exited non-zero"; }
[ -f ~/.coii/config.json ] || fail "wizard did not write config.json"
[ "$(coii config get service.log_level)" = "warning" ] \
  || fail "wizard didn't write service.log_level=warning"
[ "$(coii config get models.default)" = "anthropic/claude-haiku-4-5-20251001" ] \
  || fail "wizard didn't write models.default"
got=$(coii config get trackers.linear.team_keys --json)
echo "$got" | python3 -c 'import sys, json; v=json.load(sys.stdin); assert v==["LEL"], v' \
  || fail "wizard didn't write team_keys=[LEL]: $got"
ok "wizard wrote config.json (log_level/models.default/team_keys)"
# Resulting config must reference SecretRefs (not bake plaintext into JSON)
got=$(coii config get trackers.linear.api_key --json)
echo "$got" | grep -q '"source": *"env"' || fail "linear.api_key isn't an env SecretRef: $got"
ok "wizard preserved SecretRef shape for trackers.linear.api_key"
rm -f "$WIZARD_LOG"
# Reset to defaults for downstream sections
rm -rf ~/.coii && coii init >/dev/null

# ── 6. config CLI surface
step "coii config — file / get / set / unset / validate / audit"

[ "$(coii config file)" = "$HOME/.coii/config.json" ] || fail "config file path wrong"
ok "config file → $HOME/.coii/config.json"

# get against seeded defaults
assert_get service.name coii
ok "config get service.name = coii"

# set + get round-trip
coii config set service.log_level debug >/dev/null
assert_get service.log_level debug
ok "config set service.log_level = debug → readback"

# strict-json array
coii config set trackers.linear.team_keys '["LEL","ENG"]' --strict-json >/dev/null
got=$(coii config get trackers.linear.team_keys --json)
echo "$got" | python3 -c 'import sys, json; v=json.load(sys.stdin); assert v==["LEL","ENG"], v' \
  || fail "team_keys round-trip failed: $got"
ok "config set trackers.linear.team_keys '[\"LEL\",\"ENG\"]' (strict-json)"

# SecretRef builder mode — env source
coii config set trackers.linear.api_key --ref-source env --ref-id LINEAR_API_KEY >/dev/null
got=$(coii config get trackers.linear.api_key --json)
echo "$got" | python3 -c 'import sys, json; v=json.load(sys.stdin); assert v=={"source":"env","id":"LINEAR_API_KEY"}, v' \
  || fail "SecretRef builder result wrong: $got"
ok "config set --ref-source env --ref-id LINEAR_API_KEY"

# SecretRef builder mode — literal source
coii config set x.literal --ref-source literal --ref-value baked >/dev/null
got=$(coii config get x.literal --json)
echo "$got" | python3 -c 'import sys, json; v=json.load(sys.stdin); assert v=={"source":"literal","value":"baked"}, v' \
  || fail "literal SecretRef wrong: $got"
ok "config set --ref-source literal --ref-value <V>"
coii config unset x.literal >/dev/null

# SecretRef builder mode — file source — write a JSON file and verify
# the runtime resolves it through to a real value.
SECRETS_FILE="/tmp/coii_e2e_secrets_$$.json"
cat > "$SECRETS_FILE" <<EOF
{ "linear": { "api_key": "from-file-source" } }
EOF
coii config set trackers.linear.api_key \
  --ref-source file --ref-path "$SECRETS_FILE" --ref-key linear.api_key >/dev/null
got=$(coii config get trackers.linear.api_key --json)
echo "$got" | python3 -c '
import sys, json
v = json.load(sys.stdin)
assert v == {"source":"file","path":"'"$SECRETS_FILE"'","key":"linear.api_key"}, v
' || fail "file SecretRef wrong: $got"
# audit must consider it RESOLVED since the file exists with the right key
out=$(coii config audit 2>&1 || true)
rc=$?
[ "$rc" = "0" ] || { echo "$out" >&2; fail "file-source ref didn't resolve: rc=$rc"; }
echo "$out" | grep -q "trackers.linear.api_key" \
  && fail "file-source ref appeared in audit findings: $out" || true
ok "config set --ref-source file --ref-path PATH --ref-key K (resolves through real file)"
rm -f "$SECRETS_FILE"

# SecretRef builder mode — exec source — write a tiny script that prints the secret.
EXEC_SCRIPT="/tmp/coii_e2e_secret_cmd_$$.sh"
cat > "$EXEC_SCRIPT" <<'EOF'
#!/usr/bin/env bash
echo "from-exec-source-${1:-default}"
EOF
chmod +x "$EXEC_SCRIPT"
coii config set trackers.linear.api_key \
  --ref-source exec --ref-command "$EXEC_SCRIPT" --ref-arg arg1 >/dev/null
got=$(coii config get trackers.linear.api_key --json)
echo "$got" | python3 -c '
import sys, json
v = json.load(sys.stdin)
assert v["source"]=="exec", v
assert v["command"].endswith("'"$(basename "$EXEC_SCRIPT")"'"), v
assert v["args"] == ["arg1"], v
' || fail "exec SecretRef wrong: $got"
out=$(coii config audit 2>&1 || true)
rc=$?
[ "$rc" = "0" ] || { echo "$out" >&2; fail "exec-source ref didn't resolve: rc=$rc"; }
ok "config set --ref-source exec --ref-command <CMD> --ref-arg <A> (resolves via real exec)"
rm -f "$EXEC_SCRIPT"

# Restore the env-source ref so subsequent steps see expected shape.
coii config set trackers.linear.api_key --ref-source env --ref-id LINEAR_API_KEY >/dev/null

# unset
coii config unset service.log_level >/dev/null
[ "$(coii config get service.log_level 2>/dev/null || echo MISSING)" = "MISSING" ] \
  || fail "service.log_level still present after unset"
ok "config unset service.log_level"

# validate
coii config validate >/dev/null || fail "validate exited non-zero"
ok "config validate → exit 0"

# audit: with LINEAR_API_KEY *unset*, the env ref we built should be unresolved → exit 2
unset LINEAR_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY 2>/dev/null || true
assert_audit_exit 2 UNRESOLVED
ok "config audit (unresolved env ref) → exit 2"

# Set a literal in a secret slot → plaintext finding, exit 1
coii config set trackers.linear.webhook_secret "literal-leak" >/dev/null
assert_audit_exit 2 PLAINTEXT  # still 2 because api_key is also unresolved (rc=2 outranks)
ok "config audit (plaintext + unresolved) → exit 2 (unresolved outranks)"

# Restore api_key->env+id and remove the literal, source the env file with creds.
coii config unset trackers.linear.webhook_secret >/dev/null
coii config set trackers.linear.webhook_secret --ref-source env --ref-id LINEAR_WEBHOOK_SECRET >/dev/null

# ── 7. polling auto-start from config (the new bug-fix path)
step "polling auto-registers when trackers.linear.team_keys is in config.json"

# Long interval + a fake team key so the job *registers* but doesn't actually
# fire during the e2e window (we're not asserting Linear traffic here — that's
# e2e_polling.py's job).
coii config set trackers.linear.team_keys '["ZZZZZ"]' --strict-json >/dev/null
coii config set trackers.linear.poll_interval_seconds 86400 --strict-json >/dev/null
ok "wrote team_keys=[ZZZZZ] poll_interval_seconds=86400"

# Source .env.local_deploy if available (gives the process LINEAR_API_KEY etc.
# but the long interval still keeps us off the wire).
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
  ok "sourced credentials from $ENV_FILE"
else
  echo "  (no .env.local_deploy at $ENV_FILE — serve will run without creds)"
fi

# ── 8. serve + /health + /cron/status + /cron/run
step "coii serve --port $SERVE_PORT (host 127.0.0.1)"
coii serve --port "$SERVE_PORT" --host 127.0.0.1 >"$SERVE_LOG" 2>&1 &
SERVE_PID=$!

deadline=$(( $(date +%s) + 8 ))
health_ok=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  if curl -fsS "http://127.0.0.1:$SERVE_PORT/health" >/dev/null 2>&1; then
    health_ok=1; break
  fi
  sleep 0.3
done
if [ "$health_ok" -eq 1 ]; then
  ok "/health returned 200"
else
  echo "--- serve log:"; tail -40 "$SERVE_LOG"
  fail "/health did not respond within 8s"
fi

# /cron/status — assert linear_poll is registered (closes the polling-auto-start gap)
status_json=$(curl -fsS "http://127.0.0.1:$SERVE_PORT/cron/status")
echo "$status_json" | python3 -c '
import sys, json
d = json.load(sys.stdin)
names = [j["name"] for j in d.get("jobs", [])]
assert "linear_poll" in names, f"linear_poll job missing; saw {names}"
print(f"  jobs registered: {names}")
' || fail "linear_poll not registered (config polling-auto-start broken)"
ok "/cron/status reports linear_poll job (config-driven auto-start works)"

# POST /cron/run/{name} — manually trigger the linear_poll job. With ZZZZZ as
# team key this just makes a Linear GraphQL call that returns no events; we
# only care that the endpoint accepts the trigger and returns 200.
trigger_resp=$(curl -fsS -X POST "http://127.0.0.1:$SERVE_PORT/cron/run/linear_poll")
echo "$trigger_resp" | grep -q '"triggered":"linear_poll"' \
  || fail "POST /cron/run/linear_poll did not echo back: $trigger_resp"
ok "POST /cron/run/linear_poll → 200"

# 404 when the name doesn't exist
rc=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  "http://127.0.0.1:$SERVE_PORT/cron/run/no-such-job")
[ "$rc" = "404" ] || fail "expected 404 for unknown job, got $rc"
ok "POST /cron/run/<unknown> → 404"

# Stop the server
kill "$SERVE_PID" 2>/dev/null || true
wait "$SERVE_PID" 2>/dev/null || true
SERVE_PID=""
ok "serve stopped"

# ── 9. uninstall data
step "coii uninstall — --dry-run preserves ~/.coii"
out=$(coii uninstall --dry-run)
echo "$out" | grep -q "dry-run" || { echo "$out" >&2; fail "--dry-run didn't say so"; }
[ -e ~/.coii ] || fail "~/.coii vanished during --dry-run!"
ok "uninstall --dry-run kept ~/.coii intact"

step "coii uninstall --yes (real, removes ~/.coii AND the CLI binary)"
coii uninstall --yes
[ ! -e ~/.coii ] || fail "~/.coii still exists after uninstall"
ok "~/.coii removed"

# ── 10. binary should be gone too — `coii uninstall` shells out to
#       `uv tool uninstall coii` by default in v0.1+. We just confirm here.
step "coii CLI binary removed by uninstall"
hash -r 2>/dev/null || true
if command -v coii >/dev/null 2>&1 || [ -e "$HOME/.local/bin/coii" ]; then
  fail "coii binary still on PATH or in ~/.local/bin"
fi
ok "coii binary removed"

# ── 11. final state
step "Final state checks"
[ ! -e ~/.coii ] || fail "~/.coii reappeared"
[ ! -e "$HOME/.local/bin/coii" ] || fail "~/.local/bin/coii reappeared"
ok "everything clean"

printf '\n\033[32m✓ E2E PASSED\033[0m — install → config → serve → uninstall all clean\n'
