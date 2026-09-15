#!/usr/bin/env bash
set -euo pipefail

HOST="${1:?usage: setup-subscription-https.sh HOST}"
CONF="/etc/nginx/sites-available/ferixdi-subscription"
TLS_DIR="/etc/ferixdi/tls"
ACME="/root/.acme.sh/acme.sh"

export DEBIAN_FRONTEND=noninteractive
if ! command -v nginx >/dev/null || ! command -v curl >/dev/null || ! command -v openssl >/dev/null; then
  apt-get update -y
  apt-get install -y nginx curl openssl
fi

if [ ! -x "$ACME" ]; then
  curl -fsSL https://get.acme.sh | sh
fi
"$ACME" --set-default-ca --server letsencrypt >/dev/null

mkdir -p "$TLS_DIR"

# Port 80 is blocked upstream on this VPS. Issue through TLS-ALPN on the
# already reachable 443 instead. Xray is stopped only for the ACME handshake.
if [ ! -s "$TLS_DIR/fullchain.pem" ] || ! openssl x509 -checkend 1209600 -noout -in "$TLS_DIR/fullchain.pem" >/dev/null 2>&1; then
  restore_xray() {
    docker start ferixdi-xray >/dev/null 2>&1 || true
  }
  trap restore_xray EXIT
  docker stop ferixdi-xray >/dev/null 2>&1 || true
  "$ACME" --issue --alpn -d "$HOST" --server letsencrypt --keylength ec-256 \
    --pre-hook 'docker stop ferixdi-xray >/dev/null 2>&1 || true' \
    --post-hook 'docker start ferixdi-xray >/dev/null 2>&1 || true'
  restore_xray
  trap - EXIT

  "$ACME" --install-cert -d "$HOST" --ecc \
    --key-file "$TLS_DIR/key.pem" \
    --fullchain-file "$TLS_DIR/fullchain.pem" \
    --reloadcmd 'nginx -t && systemctl reload nginx'
fi

# Free public 8080 for nginx. The Telegram bot is restarted later on 18080.
systemctl stop ferixdi-bot >/dev/null 2>&1 || true

cat > "$CONF" <<EOF
server {
    listen 8080 ssl;
    listen [::]:8080 ssl;
    server_name ${HOST};

    ssl_certificate ${TLS_DIR}/fullchain.pem;
    ssl_certificate_key ${TLS_DIR}/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 5s;
        proxy_read_timeout 15s;
    }
}
EOF

ln -sfn "$CONF" /etc/nginx/sites-enabled/ferixdi-subscription
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx
ufw allow 8080/tcp || true

echo "HTTPS subscription endpoint ready: https://${HOST}:8080"
