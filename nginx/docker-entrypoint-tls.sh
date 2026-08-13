#!/bin/sh
# Ensure a TLS certificate exists before nginx starts.
#
# A real deployment mounts a CA-issued certificate over /etc/nginx/tls. When
# nothing is mounted — local development, a first `docker compose up` — a
# self-signed certificate is generated so the stack is HTTPS-only from the
# very first run instead of silently falling back to plaintext.
set -eu

TLS_DIR="${TLS_DIR:-/etc/nginx/tls}"
CERT="$TLS_DIR/server.crt"
KEY="$TLS_DIR/server.key"
CN="${TLS_COMMON_NAME:-localhost}"

if [ ! -s "$CERT" ] || [ ! -s "$KEY" ]; then
    echo "nginx: no TLS certificate at $CERT — generating a self-signed one for '$CN'." >&2
    echo "nginx: mount a CA-issued certificate at $TLS_DIR for production." >&2
    mkdir -p "$TLS_DIR"
    openssl req -x509 -nodes -newkey rsa:2048 \
        -days "${TLS_SELF_SIGNED_DAYS:-365}" \
        -keyout "$KEY" -out "$CERT" \
        -subj "/CN=$CN" \
        -addext "subjectAltName=DNS:$CN,DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
    chmod 600 "$KEY"
fi

exec "$@"
