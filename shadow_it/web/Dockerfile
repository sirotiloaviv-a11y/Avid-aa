# Build from the web/ directory:
#   docker build -t shadow-it-web web/
FROM node:22-alpine AS deps
WORKDIR /app
# package-lock.json is optional here: the repo ships without one, and `npm ci`
# requires it. Once you have run `npm install` locally, commit the lockfile and
# this switches to the reproducible path automatically.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S nodejs && adduser -S -u 10001 -G nodejs nextjs

# `output: "standalone"` emits a server plus only the node_modules actually
# reached, so the runtime image carries a fraction of the dependency tree.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# Node 22 has global fetch, so the image needs no curl to check itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
