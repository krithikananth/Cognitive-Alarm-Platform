FROM nginx:1.30-alpine

# openssl provides the fallback self-signed certificate when no CA-issued one
# is mounted, so the edge is never reachable over plaintext by accident.
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/tls \
    && chown -R nginx:nginx /etc/nginx/tls

COPY nginx.conf /etc/nginx/nginx.conf
COPY --chmod=0755 docker-entrypoint-tls.sh /usr/local/bin/docker-entrypoint-tls.sh

# Origin serving the hashed frontend assets when they are fronted by a CDN
# (must match the frontend image's PUBLIC_URL). The CSP is otherwise
# same-origin only, so without this the CDN's responses would be blocked.
# Baked at build time rather than read at runtime because the container's
# filesystem is read-only in production.
ARG CDN_ORIGIN=
RUN if [ -n "$CDN_ORIGIN" ]; then \
        sed -i \
            -e "s|script-src 'self'|script-src 'self' $CDN_ORIGIN|" \
            -e "s|style-src 'self'|style-src 'self' $CDN_ORIGIN|" \
            -e "s|img-src 'self'|img-src 'self' $CDN_ORIGIN|" \
            -e "s|font-src 'self'|font-src 'self' $CDN_ORIGIN|" \
            -e "s|connect-src 'self'|connect-src 'self' $CDN_ORIGIN|" \
            /etc/nginx/nginx.conf; \
    fi

USER nginx

# 8080 serves only the permanent redirect to HTTPS; 8443 serves the app.
EXPOSE 8080 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/nginx-health || exit 1

ENTRYPOINT ["docker-entrypoint-tls.sh", "nginx", "-g", "daemon off;"]