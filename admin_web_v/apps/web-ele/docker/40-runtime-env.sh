#!/bin/sh
set -eu

RUNTIME_CONFIG_FILE="/usr/share/nginx/html/runtime-config.js"
VITE_ADMIN_API_BASE_VALUE="${VITE_ADMIN_API_BASE:-/api/admin}"
ESCAPED_VALUE=$(printf '%s' "$VITE_ADMIN_API_BASE_VALUE" | sed 's/\\/\\\\/g; s/"/\\"/g')

cat > "$RUNTIME_CONFIG_FILE" <<EOF
window.__APP_CONFIG__ = Object.assign({}, window.__APP_CONFIG__, {
  VITE_ADMIN_API_BASE: "$ESCAPED_VALUE"
});
EOF

