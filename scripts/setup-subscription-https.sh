#!/usr/bin/env bash
set -euo pipefail

HOST="${1:?usage: setup-subscription-https.sh HOST}"
PUBLIC_IP="${HOST%.sslip.io}"
PUBLIC_IP="${PUBLIC_IP//-/.}"
HTTPS_BACKEND_PORT=9443
XRAY_443_BACKEND_PORT=10443
CONF="/etc/nginx/sites-available/ferixdi-subscription"
STREAM_CONF="/etc/nginx/modules-enabled/99-ferixdi-stream.conf"
TLS_DIR="/etc/ferixdi/tls"
ACME="/root/.acme.sh/acme.sh"

export DEBIAN_FRONTEND=noninteractive
if ! command -v nginx >/dev/null || ! command -v curl >/dev/null || ! command -v openssl >/dev/null; then
  apt-get update -y
  apt-get install -y nginx curl openssl
fi
if ! nginx -V 2>&1 | grep -q -- '--with-stream=dynamic' && [ ! -e /usr/lib/nginx/modules/ngx_stream_module.so ]; then
  apt-get update -y
  apt-get install -y libnginx-mod-stream
elif [ ! -e /usr/lib/nginx/modules/ngx_stream_module.so ]; then
  apt-get update -y
  apt-get install -y libnginx-mod-stream
fi

if [ ! -x "$ACME" ]; then
  curl -fsSL https://get.acme.sh | sh
fi
"$ACME" --set-default-ca --server letsencrypt >/dev/null
mkdir -p "$TLS_DIR"

# The public :443 socket is owned by nginx after this migration. For certificate
# renewal we temporarily stop nginx so acme.sh can answer TLS-ALPN directly.
if [ ! -s "$TLS_DIR/fullchain.pem" ] || ! openssl x509 -checkend 1209600 -noout -in "$TLS_DIR/fullchain.pem" >/dev/null 2>&1; then
  systemctl stop nginx >/dev/null 2>&1 || true
  restore_nginx() { systemctl start nginx >/dev/null 2>&1 || true; }
  trap restore_nginx EXIT
  "$ACME" --issue --alpn -d "$HOST" --server letsencrypt --keylength ec-256 --force
  trap - EXIT

  "$ACME" --install-cert -d "$HOST" --ecc \
    --key-file "$TLS_DIR/key.pem" \
    --fullchain-file "$TLS_DIR/fullchain.pem" \
    --reloadcmd 'nginx -t && systemctl reload nginx'
fi

# HTTPS terminates only on localhost. Public TCP/443 is a TLS SNI router:
# - our subscription hostname -> local nginx HTTPS -> Telegram bot
# - every other SNI (Reality uses www.microsoft.com) -> local Xray backend
cat > "$CONF" <<EOF
server {
    listen 127.0.0.1:${HTTPS_BACKEND_PORT} ssl;
    server_name ${HOST};

    ssl_certificate ${TLS_DIR}/fullchain.pem;
    ssl_certificate_key ${TLS_DIR}/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8080;
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

cat > "$STREAM_CONF" <<EOF
stream {
    map \$ssl_preread_server_name \$ferixdi_backend {
        ${HOST} 127.0.0.1:${HTTPS_BACKEND_PORT};
        default 127.0.0.1:${XRAY_443_BACKEND_PORT};
    }

    server {
        listen ${PUBLIC_IP}:443 reuseport;
        proxy_pass \$ferixdi_backend;
        ssl_preread on;
        proxy_connect_timeout 5s;
        proxy_timeout 300s;
    }
}
EOF

ln -sfn "$CONF" /etc/nginx/sites-enabled/ferixdi-subscription
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

ufw allow 443/tcp || true
ufw delete allow 9443/tcp >/dev/null 2>&1 || true
ufw delete allow 8080/tcp >/dev/null 2>&1 || true

echo "Standard HTTPS subscription endpoint ready: https://${HOST}"
echo "Shared 443 routing: ${HOST} -> HTTPS; other SNI -> Xray 127.0.0.1:${XRAY_443_BACKEND_PORT}"
