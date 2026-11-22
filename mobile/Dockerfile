# The web app for `docker compose --profile app up` (docker-compose.yml): the same static export
# Vercel builds (vercel.json), served with the same fallback to index.html for app routes.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Built into the bundle, like on Vercel: the address the browser uses to reach the API.
ARG EXPO_PUBLIC_API_URL=http://localhost:8000
ENV EXPO_PUBLIC_API_URL=$EXPO_PUBLIC_API_URL
RUN npx expo export --platform web

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
