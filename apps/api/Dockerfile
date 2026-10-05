# Build context: repository root (go.mod lives there).  docker build -f apps/api/Dockerfile .
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/api ./apps/api/cmd/server

FROM alpine:3.20
RUN adduser -D -u 10001 zippy && apk add --no-cache ca-certificates wget
USER zippy
COPY --from=build /out/api /usr/local/bin/api
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 CMD wget -qO- http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["api"]
