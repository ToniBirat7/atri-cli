# syntax=docker/dockerfile:1.7
FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY next-env.d.ts next.config.ts postcss.config.mjs tsconfig.json ./
COPY public ./public
COPY src ./src
RUN npm run build

EXPOSE 3000

CMD ["node", ".next/standalone/server.js"]