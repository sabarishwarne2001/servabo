#!/usr/bin/env bash
# Start (or restart) what the browser tests need besides the web app:
# the Servabo API, the background worker, the local mail catcher and, with
# E2E_GATEWAY=dodo (the default), the stand-in Dodo Payments the API bills through.
#
#   frontend/e2e/scripts/start-stack.sh          # start / restart all three
#   frontend/e2e/scripts/start-stack.sh stop     # stop them
#
# Needs: Postgres (with pgvector) and Redis already running, backend/.venv,
# and backend/.env prepared for e2e (see frontend/e2e/README.md). The script
# migrates the database, then starts the processes in the background with
# their logs in $E2E_LOG_DIR (default /tmp/servabo-e2e-logs).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
BACKEND="$REPO/backend"
LOG_DIR="${E2E_LOG_DIR:-/tmp/servabo-e2e-logs}"
RUN_DIR="$LOG_DIR/pids"
PY="${E2E_PYTHON:-$BACKEND/.venv/bin/python}"
API_PORT="${E2E_API_PORT:-8000}"
mkdir -p "$LOG_DIR" "$RUN_DIR"

stop_one() {
  local name="$1" pidfile="$RUN_DIR/$1.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
    echo "stopped $name"
  fi
}

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

stop_all() {
  stop_one api
  stop_one worker
  stop_one smtp
  stop_one llm
  stop_one dns
  stop_one dodo
  stop_one zoho
}

if [[ "${1:-}" == "stop" ]]; then
  stop_all
  exit 0
fi

stop_all
if port_busy "$API_PORT"; then
  echo "port $API_PORT is already in use by a process this script did not start; stop it first" >&2
  exit 1
fi

cd "$BACKEND"
echo "migrating database..."
ARCH40_CONTRACT=1 "$PY" -m alembic upgrade head >"$LOG_DIR/migrate.log" 2>&1 || {
  tail -20 "$LOG_DIR/migrate.log" >&2
  exit 1
}

if ! port_busy 1025; then
  nohup node "$HERE/../support/smtp-sink.mjs" >"$LOG_DIR/smtp.log" 2>&1 &
  echo $! >"$RUN_DIR/smtp.pid"
fi

# E2E_LLM=1: a deterministic local model stand-in (support/llm-mock.mjs) behind the sovereign
# edition's local-model setting, so extraction, verification, the review queue and the assistant
# run end to end without a provider key. Unset: no model, as in the sandbox before (F-063).
if [[ "${E2E_LLM:-}" == "1" ]]; then
  LLM_PORT="${E2E_LLM_PORT:-11434}"
  if ! port_busy "$LLM_PORT"; then
    E2E_LLM_PORT="$LLM_PORT" nohup node "$HERE/../support/llm-mock.mjs" >"$LOG_DIR/llm.log" 2>&1 &
    echo $! >"$RUN_DIR/llm.pid"
  fi
  export LOCAL_LLM_MODE=exclusive
  export LOCAL_LLM_BASE_URL="http://127.0.0.1:$LLM_PORT/v1"
  export LOCAL_LLM_MODEL="${E2E_LLM_MODEL:-servabo-e2e-local}"
  export LOCAL_LLM_TIMEOUT_SECONDS=30
fi

# Campaign session 4: a DNS server for domain verification (backend/scripts/e2e_dns.py), answering
# TXT queries from records the journeys publish; the API asks it instead of public resolvers.
DNS_PORT="${E2E_DNS_PORT:-5354}"
export E2E_DNS_RECORDS="${E2E_DNS_RECORDS:-$LOG_DIR/dns-records.json}"
[[ -f "$E2E_DNS_RECORDS" ]] || echo '{}' >"$E2E_DNS_RECORDS"
nohup "$PY" -m scripts.e2e_dns serve --port "$DNS_PORT" --records "$E2E_DNS_RECORDS" >"$LOG_DIR/dns.log" 2>&1 &
echo $! >"$RUN_DIR/dns.pid"
export DNS_RESOLVERS="127.0.0.1:$DNS_PORT"

# Website and payments session (C1): the journeys bill through Dodo by default, the production
# gateway. A stand-in Dodo (backend/tests/fakes/fake_dodo.py) serves its API, its checkout page and
# its customer portal on E2E_DODO_PORT, and sends signed webhooks to the API like Dodo does.
# E2E_GATEWAY=stripe keeps the Stripe journeys (scripts/e2e_stand_in.py plays Stripe's side).
E2E_GATEWAY="$(echo "${E2E_GATEWAY:-dodo}" | tr '[:upper:]' '[:lower:]')"
export E2E_GATEWAY
if [[ "$E2E_GATEWAY" == "dodo" ]]; then
  DODO_PORT="${E2E_DODO_PORT:-8790}"
  if port_busy "$DODO_PORT"; then
    echo "port $DODO_PORT is already in use by a process this script did not start; stop it first" >&2
    exit 1
  fi
  export E2E_DODO_URL="http://127.0.0.1:$DODO_PORT"
  nohup "$PY" -m tests.fakes.fake_dodo --port "$DODO_PORT" \
    --webhook-url "http://127.0.0.1:$API_PORT/api/v1/billing/webhooks/dodo" >"$LOG_DIR/dodo.log" 2>&1 &
  echo $! >"$RUN_DIR/dodo.pid"
  export BILLING_GATEWAY=DODO DODO_API_BASE="$E2E_DODO_URL" DODO_LIVEMODE=false
  export DODO_API_KEY="${E2E_DODO_API_KEY:-e2e_dodo_test_key}"
  # Session H: the GST Credit add-on is for sale (the stand-in is given this product by `dodo-catalogue`).
  export DODO_ADDON_PRODUCT_GST_CREDIT="${DODO_ADDON_PRODUCT_GST_CREDIT:-pdt_e2e_gst_credit}"
  DODO_WEBHOOK_SECRET="$("$PY" -c 'from tests.fakes.fake_dodo import DEFAULT_SECRET; print(DEFAULT_SECRET)')"
  export DODO_WEBHOOK_SECRET
else
  export BILLING_GATEWAY=STRIPE
fi

# Final session 1 (2B): email-in. The API accepts Postmark's inbound webhook with this basic-auth credential, and the
# workspace addresses take the stand-in's inbound hash (tests/fakes/fake_postmark_inbound.py). `e2e_stand_in.py
# inbound-email` plays Postmark against it.
export POSTMARK_INBOUND_WEBHOOK_USER="$("$PY" -c 'from tests.fakes.fake_postmark_inbound import DEFAULT_USER; print(DEFAULT_USER)')"
export POSTMARK_INBOUND_WEBHOOK_PASSWORD="$("$PY" -c 'from tests.fakes.fake_postmark_inbound import DEFAULT_PASSWORD; print(DEFAULT_PASSWORD)')"
export POSTMARK_INBOUND_HASH="$("$PY" -c 'from tests.fakes.fake_postmark_inbound import DEFAULT_HASH; print(DEFAULT_HASH)')"
export E2E_API_ORIGIN="http://127.0.0.1:$API_PORT"

# Final session 1 (3C): a stand-in Zoho (backend/tests/fakes/fake_zoho.py): its consent screen approves at once and sends the browser
# back to the API's callback; its token, revoke and organizations endpoints answer as Zoho's do. The API is pointed at it by the
# test-only overrides (refused when ENVIRONMENT=production).
ZOHO_PORT="${E2E_ZOHO_PORT:-8791}"
if ! port_busy "$ZOHO_PORT"; then
  nohup "$PY" -m tests.fakes.fake_zoho --port "$ZOHO_PORT" >"$LOG_DIR/zoho.log" 2>&1 &
  echo $! >"$RUN_DIR/zoho.pid"
fi
export E2E_ZOHO_URL="http://127.0.0.1:$ZOHO_PORT"
export ZOHO_CLIENT_ID="1000.E2EAPPCLIENT" ZOHO_CLIENT_SECRET="e2e-zoho-secret-0123456789abcdef"
export ZOHO_REDIRECT_URI="http://127.0.0.1:$API_PORT/api/v1/erp/zoho/callback"
export ZOHO_ACCOUNTS_URL_OVERRIDE="$E2E_ZOHO_URL" ZOHO_API_URL_OVERRIDE="$E2E_ZOHO_URL"

nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$LOG_DIR/api.log" 2>&1 &
echo $! >"$RUN_DIR/api.pid"

nohup "$PY" -m app.worker --loop all --profile all --log-level INFO >"$LOG_DIR/worker.log" 2>&1 &
echo $! >"$RUN_DIR/worker.pid"

for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null; then
    echo "API healthy on :$API_PORT (logs in $LOG_DIR)"
    exit 0
  fi
  if ! kill -0 "$(cat "$RUN_DIR/api.pid")" 2>/dev/null; then
    echo "the API exited during start-up:" >&2
    tail -30 "$LOG_DIR/api.log" >&2
    exit 1
  fi
  sleep 2
done
echo "the API did not become healthy in 180 s" >&2
tail -30 "$LOG_DIR/api.log" >&2
exit 1
