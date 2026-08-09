#!/usr/bin/env bash
# ============================================================
# Quantiva HTTPS ??????Let's Encrypt + certbot + Nginx?
# ??: sudo bash deploy/scripts/setup_https.sh your.domain.com
# ============================================================
set -euo pipefail

DOMAIN="${1:???: setup_https.sh your.domain.com}"
EMAIL="${2:-admin@${DOMAIN}}"
NGINX_CONF="/etc/nginx/sites-available/quantumx"
WEBROOT="/var/www/quantumx"

echo "==> 1/5 ????"
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx

echo "==> 2/5 ?? Webroot ??"
mkdir -p "$WEBROOT"
chown -R www-data:www-data "$WEBROOT"

echo "==> 3/5 ???? Nginx ???HTTP?"
cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    root $WEBROOT;
    location /.well-known/acme-challenge/ { root $WEBROOT; }
    location / {
        proxy_pass http://127.0.0.1:8686;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/quantumx
nginx -t && systemctl reload nginx

echo "==> 4/5 ?? Let's Encrypt ????????? certbot ???????"
certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --non-interactive --redirect

echo "==> 5/5 ??"
echo "HTTPS ???: https://$DOMAIN"
echo "????: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "????: systemctl list-timers | grep certbot"
