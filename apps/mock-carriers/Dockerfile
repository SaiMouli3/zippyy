# Build context: repository root.  docker build -f apps/mock-carriers/Dockerfile .
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/mock-carriers ./apps/mock-carriers/cmd

FROM alpine:3.20
RUN adduser -D -u 10001 mock && apk add --no-cache ca-certificates wget
USER mock
COPY --from=build /out/mock-carriers /usr/local/bin/mock-carriers
EXPOSE 9000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 CMD wget -qO- http://127.0.0.1:9000/health || exit 1
ENTRYPOINT ["mock-carriers"]
