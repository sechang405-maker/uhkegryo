FROM node:22-bookworm-slim AS dependencies

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM dependencies AS build

ARG AGENT_API_ORIGIN=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=/api
ARG NEXT_PUBLIC_UI_DEMO=0
ARG PORTFOLIO_MODE=0
ENV AGENT_API_ORIGIN=${AGENT_API_ORIGIN}
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_UI_DEMO=${NEXT_PUBLIC_UI_DEMO}
ENV PORTFOLIO_MODE=${PORTFOLIO_MODE}
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/ ./
COPY docs/domains/illustration-reference/term-cards/ /app/docs/domains/illustration-reference/term-cards/
RUN npm run build

FROM node:22-bookworm-slim AS runtime

WORKDIR /app/frontend
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app/frontend/package.json /app/frontend/package-lock.json ./
COPY --from=build --chown=node:node /app/frontend/node_modules ./node_modules
COPY --from=build --chown=node:node /app/frontend/.next ./.next
COPY --from=build --chown=node:node /app/frontend/public ./public
COPY --from=build --chown=node:node /app/frontend/next.config.mjs ./next.config.mjs
COPY --from=build --chown=node:node /app/docs /app/docs
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-p", "3000", "-H", "0.0.0.0"]
