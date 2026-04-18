#!/bin/sh
set -eu

json_escape() {
  printf '%s' "${1:-}" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

: "${BACKEND_UPSTREAM:=http://backend.screening.internal:8000}"
: "${VITE_SCREENING_API_BASE_URL:=/api/v1}"
: "${VITE_SCREENING_POLL_INTERVAL_MS:=750}"
: "${VITE_SCREENING_JOB_TIMEOUT_MS:=90000}"
: "${VITE_AUTH_ENABLED:=false}"
: "${VITE_OIDC_AUTHORITY:=}"
: "${VITE_OIDC_CLIENT_ID:=}"
: "${VITE_OIDC_REDIRECT_URI:=}"
: "${VITE_OIDC_POST_LOGOUT_REDIRECT_URI:=}"
: "${VITE_OIDC_SCOPE:=openid profile email}"
: "${VITE_OIDC_IDLE_TIMEOUT_MS:=900000}"
: "${VITE_OIDC_CLEAR_SESSION_ON_CLOSE:=true}"
: "${VITE_ACTIMIZE_REVIEW_ALERT_URL:=}"
: "${NGINX_DNS_RESOLVER:=169.254.169.253}"
: "${NGINX_CLIENT_MAX_BODY_SIZE:=25m}"

cat >/usr/share/nginx/html/app-config.js <<EOF
window.__APP_CONFIG__ = {
  VITE_SCREENING_API_BASE_URL: "$(json_escape "$VITE_SCREENING_API_BASE_URL")",
  VITE_SCREENING_POLL_INTERVAL_MS: "$(json_escape "$VITE_SCREENING_POLL_INTERVAL_MS")",
  VITE_SCREENING_JOB_TIMEOUT_MS: "$(json_escape "$VITE_SCREENING_JOB_TIMEOUT_MS")",
  VITE_AUTH_ENABLED: "$(json_escape "$VITE_AUTH_ENABLED")",
  VITE_OIDC_AUTHORITY: "$(json_escape "$VITE_OIDC_AUTHORITY")",
  VITE_OIDC_CLIENT_ID: "$(json_escape "$VITE_OIDC_CLIENT_ID")",
  VITE_OIDC_REDIRECT_URI: "$(json_escape "$VITE_OIDC_REDIRECT_URI")",
  VITE_OIDC_POST_LOGOUT_REDIRECT_URI: "$(json_escape "$VITE_OIDC_POST_LOGOUT_REDIRECT_URI")",
  VITE_OIDC_SCOPE: "$(json_escape "$VITE_OIDC_SCOPE")",
  VITE_OIDC_IDLE_TIMEOUT_MS: "$(json_escape "$VITE_OIDC_IDLE_TIMEOUT_MS")",
  VITE_OIDC_CLEAR_SESSION_ON_CLOSE: "$(json_escape "$VITE_OIDC_CLEAR_SESSION_ON_CLOSE")",
  VITE_ACTIMIZE_REVIEW_ALERT_URL: "$(json_escape "$VITE_ACTIMIZE_REVIEW_ALERT_URL")"
};
EOF

cat >/etc/nginx/conf.d/default.conf <<EOF
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {
    client_max_body_size ${NGINX_CLIENT_MAX_BODY_SIZE};
    resolver ${NGINX_DNS_RESOLVER} ipv6=off valid=10s;
    set \$backend_upstream ${BACKEND_UPSTREAM};
    proxy_pass \$backend_upstream;
    proxy_http_version 1.1;
    proxy_connect_timeout 180s;
    proxy_send_timeout 180s;
    proxy_read_timeout 180s;
    send_timeout 180s;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }

  location / {
    try_files \$uri /index.html;
  }
}
EOF

exec nginx -g 'daemon off;'
