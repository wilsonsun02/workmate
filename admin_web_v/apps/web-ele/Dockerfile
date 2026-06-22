FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable

COPY . .

RUN pnpm install --frozen-lockfile
RUN pnpm build:ele

FROM nginx:1.27-alpine

COPY apps/web-ele/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/web-ele/docker/40-runtime-env.sh /docker-entrypoint.d/40-runtime-env.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-env.sh

COPY --from=builder /app/apps/web-ele/dist /usr/share/nginx/html

EXPOSE 80

