FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

ARG REACT_APP_API_URL=/api/v1
ARG REACT_APP_FIREBASE_API_KEY
ARG REACT_APP_FIREBASE_AUTH_DOMAIN
ARG REACT_APP_FIREBASE_PROJECT_ID
ARG REACT_APP_FIREBASE_STORAGE_BUCKET
ARG REACT_APP_FIREBASE_MESSAGING_SENDER_ID
ARG REACT_APP_FIREBASE_APP_ID
ARG REACT_APP_FIREBASE_VAPID_KEY

# Absolute origin to prefix every hashed asset URL with, e.g.
# https://cdn.example.com. Empty (the default) keeps assets same-origin and the
# image self-contained; setting it makes index.html point at a CDN while this
# container remains the origin the CDN pulls from.
ARG PUBLIC_URL=

# INLINE_RUNTIME_CHUNK=false: CRA inlines the webpack runtime into index.html
# by default, which would force script-src 'unsafe-inline' in the CSP. Emitting
# it as a file instead keeps the policy strict.
# GENERATE_SOURCEMAP=false: maps are not served in production, and emitting
# them roughly doubles the size of the build context copied into the runtime.
ENV REACT_APP_API_URL=$REACT_APP_API_URL \
	REACT_APP_FIREBASE_API_KEY=$REACT_APP_FIREBASE_API_KEY \
	REACT_APP_FIREBASE_AUTH_DOMAIN=$REACT_APP_FIREBASE_AUTH_DOMAIN \
	REACT_APP_FIREBASE_PROJECT_ID=$REACT_APP_FIREBASE_PROJECT_ID \
	REACT_APP_FIREBASE_STORAGE_BUCKET=$REACT_APP_FIREBASE_STORAGE_BUCKET \
	REACT_APP_FIREBASE_MESSAGING_SENDER_ID=$REACT_APP_FIREBASE_MESSAGING_SENDER_ID \
	REACT_APP_FIREBASE_APP_ID=$REACT_APP_FIREBASE_APP_ID \
	REACT_APP_FIREBASE_VAPID_KEY=$REACT_APP_FIREBASE_VAPID_KEY \
	PUBLIC_URL=$PUBLIC_URL \
	INLINE_RUNTIME_CHUNK=false \
	GENERATE_SOURCEMAP=false

COPY . .

# `npm run build` also emits the .br/.gz siblings that nginx serves via
# brotli_static/gzip_static, and the budget check fails the image build rather
# than shipping a bundle that regressed.
RUN npm run build && npm run check:bundle-size

# Alpine's own nginx is used instead of the nginx.org image because only Alpine
# packages a prebuilt brotli module; nginx.org publishes no brotli package.
FROM alpine:3.20 AS runtime

RUN apk add --no-cache nginx nginx-mod-http-brotli

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build --chown=nginx:nginx /app/build /usr/share/nginx/html

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
	CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["nginx", "-g", "daemon off;"]
