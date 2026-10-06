#!/usr/bin/env bash
# Run the full stack WITHOUT Docker against a local PostgreSQL + Redis (useful where Docker is unavailable).
#   scripts/dev-local.sh start|stop|status
# Requires: Postgres reachable at $DATABASE_URL, Redis at $REDIS_URL, Go, Node.
set -euo pipefail
cd "$(dirname "$0")/.."
RUN=.run; mkdir -p "$RUN" bin
export DATABASE_URL=${DATABASE_URL:-postgres://zippy:zippy@localhost:5432/zippy?sslmode=disable}
export REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}
export FASTSHIP_BASE_URL=http://localhost:9000 QUICKEXPRESS_BASE_URL=http://localhost:9000 RELIABLECOURIER_BASE_URL=http://localhost:9000
export ZIPPY_PUBLIC_URL=http://localhost:8080 ZIPPY_WEBHOOK_BASE=http://localhost:8080
export FASTSHIP_WEBHOOK_SECRET=dev-fastship-secret QUICKEXPRESS_WEBHOOK_SECRET=dev-quickexpress-secret RELIABLE_WEBHOOK_SECRET=dev-reliable-secret
export WEBHOOK_SIGNATURE_REQUIRED=true SEED_DEMO=${SEED_DEMO:-true}

start_bg() { # name cmd...
  local name=$1; shift
  setsid nohup "$@" > "$RUN/$name.log" 2>&1 < /dev/null &
  echo $! > "$RUN/$name.pid"
}
case "${1:-start}" in
  start)
    go build -o bin/api ./apps/api/cmd/server
    go build -o bin/mock-carriers ./apps/mock-carriers/cmd
    PORT=9000 start_bg mock ./bin/mock-carriers
    PORT=8080 start_bg api ./bin/api
    (cd apps/web && start_bg_web=1; setsid nohup npx vite --host 0.0.0.0 > ../../$RUN/web.log 2>&1 < /dev/null & echo $! > ../../$RUN/web.pid)
    echo "started: web http://localhost:5173  api http://localhost:8080  mock-carriers http://localhost:9000 (logs in $RUN/)";;
  stop)
    for f in "$RUN"/*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; done; echo stopped;;
  status)
    for f in "$RUN"/*.pid; do [ -f "$f" ] && echo "$(basename "$f" .pid): $(kill -0 "$(cat "$f")" 2>/dev/null && echo up || echo down)"; done;;
esac
