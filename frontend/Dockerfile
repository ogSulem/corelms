FROM node:20-slim AS builder

WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install

COPY . .
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_QUICKSTART_ASSET_ID
ARG NEXT_PUBLIC_QUICKSTART_VIDEO_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_QUICKSTART_ASSET_ID=$NEXT_PUBLIC_QUICKSTART_ASSET_ID
ENV NEXT_PUBLIC_QUICKSTART_VIDEO_URL=$NEXT_PUBLIC_QUICKSTART_VIDEO_URL
RUN yarn build

FROM node:20-slim

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/package.json ./package.json

EXPOSE 3000

USER node
CMD ["yarn", "start"]
