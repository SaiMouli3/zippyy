.PHONY: up down logs build test test-go test-web test-integration vet fmt smoke web-build dev-local dev-stop

up:            ## start everything (UI :3000, API :8080, mock carriers :9000)
	docker compose up --build

down:
	docker compose down -v

build:
	go build ./... && cd apps/web && npm ci && npm run build

fmt:
	gofmt -l apps tests migrations docs

vet:
	go vet ./...

# Unit tests need nothing; integration tests (tests/) need PostgreSQL and skip themselves when it is absent.
test: test-go test-web

test-go:
	go test ./... -count=1

# Start Postgres in Docker, create the test DB, run everything.
test-integration:
	docker compose up -d postgres
	until docker compose exec -T postgres pg_isready -U zippy >/dev/null 2>&1; do sleep 1; done
	docker compose exec -T postgres psql -U zippy -d postgres -c "CREATE DATABASE zippy_test" || true
	TEST_DATABASE_URL="postgres://zippy:zippy@localhost:5432/zippy_test?sslmode=disable" go test ./tests/ -count=1 -v

test-web:
	cd apps/web && npm ci && npm test && npm run typecheck

smoke:         ## full demo scenario against a running stack
	./scripts/smoke.sh

dev-local:     ## no Docker: needs local Postgres + Redis (see scripts/dev-local.sh)
	./scripts/dev-local.sh start

dev-stop:
	./scripts/dev-local.sh stop
