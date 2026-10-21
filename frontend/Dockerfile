FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Rewrites are compiled at build time: /api/v1/* is proxied to BACKEND_URL, so it must be the address the
# frontend server (not the browser) uses to reach the API.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
# Legacy sandbox pages (/orders, /mock) call the backend from the browser.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S zippy && adduser -S zippy -G zippy
COPY --from=build --chown=zippy:zippy /app/.next/standalone ./
COPY --from=build --chown=zippy:zippy /app/.next/static ./.next/static
COPY --from=build --chown=zippy:zippy /app/public ./public
USER zippy
EXPOSE 3000
CMD ["node", "server.js"]
