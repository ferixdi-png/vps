#!/usr/bin/env bash
set -euo pipefail

HOST="${1:?usage: setup-subscription-https.sh HOST}"
ACME_ROOT="/var/www/ferixdi-acme"
CONF="/etc/nginx/sites-available/ferixdi-subscription"

export DEBIAN_FRONTEND=noninteractive
if ! command -v nginx >/dev/null || ! command -v certbot >/dev/null; then
  apt-get update -y
  apt-get install -y nginx certbot
fi

mkdir -p "$ACME_ROOT/.well-known/acme-challenge"

cat > "$CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${HOST};

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type text/plain;
    }

    location / {
        return 404;
    }
}
EOF

ln -sfn "$CONF" /etc/nginx/sites-enabled/ferixdi-subscription
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if [ ! -s "/etc/letsencrypt/live/${HOST}/fullchain.pem" ] || ! certbot certificates 2>/dev/null | grep -A6 "Certificate Name: ${HOST}" | grep -q 'VALID:'; then
  certbot certonly \
    --webroot -w "$ACME_ROOT" \
    -d "$HOST" \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email \
    --keep-until-expiring
fi

cat > "$CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${HOST};

    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type text/plain;
    }

    location / {
        return 404;
    }
}

server {
    listen 9443 ssl;
    listen [::]:9443 ssl;
    server_name ${HOST};

    ssl_certificate /etc/letsencrypt/live/${HOST}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${HOST}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 5s;
        proxy_read_timeout 15s;
    }
}
EOF

mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/usr/bin/env bash
set -e
nginx -t
systemctl reload nginx
EOF
chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

nginx -t
systemctl reload nginx

echo "HTTPS subscription endpoint ready: https://${HOST}:9443"
