#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "setup.sh must run as root (it writes nginx, cron and /etc config)." >&2
    exit 1
fi
for binary in python3 nginx openssl; do
    command -v "$binary" >/dev/null || { echo "missing required binary: $binary" >&2; exit 1; }
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_DIR=/etc/vps-visibility

prompt() {
    local var="$1" text="$2" secret="${3:-}"
    if [[ -z "${!var:-}" ]]; then
        if [[ -n "$secret" ]]; then
            read -rsp "$text" "$var"; echo
        else
            read -rp "$text" "$var"
        fi
    fi
}

prompt VV_DOMAIN "Dashboard domain (e.g. vps.example.com): "
prompt VV_AUTH_USER "Basic auth username: "
prompt VV_AUTH_PASS "Basic auth password: " secret
# Only ask when the variable is unset: VV_TG_TOKEN= means "no alerts, do not ask".
if [[ -z "${VV_TG_TOKEN+set}" ]]; then
    read -rp "Telegram bot token (enter to skip alerts): " VV_TG_TOKEN
fi
VV_TG_CHAT="${VV_TG_CHAT-}"
if [[ -n "$VV_TG_TOKEN" && -z "$VV_TG_CHAT" ]]; then
    read -rp "Telegram chat id: " VV_TG_CHAT
fi
VV_DATA_DIR="${VV_DATA_DIR:-/var/lib/vps-visibility}"

mkdir -p "$CONF_DIR" "$VV_DATA_DIR/public/history"
# nginx workers read the htpasswd and the JSON, so these must stay traversable
# whatever umask root happens to run with.
chmod 755 "$CONF_DIR" "$VV_DATA_DIR" "$VV_DATA_DIR/public" "$VV_DATA_DIR/public/history"

if [[ ! -f "$CONF_DIR/config.json" ]]; then
    # The bot token lands in here. The umask keeps it unreadable to everyone but
    # root from the start, including the moment between creation and the chmod.
    (
        umask 077
        python3 - "$VV_DOMAIN" "$VV_DATA_DIR" "$VV_TG_TOKEN" "$VV_TG_CHAT" > "$CONF_DIR/config.json" <<'PY'
import json, sys
domain, data_dir, token, chat = sys.argv[1:5]
print(json.dumps({
    "schema_version": 1,
    "dashboard_domain": domain,
    "data_dir": data_dir,
    "retention_days": 14,
    "probe_via": "localhost",
    "public_ip": None,
    "filesystems": ["/"],
    "thresholds": {"disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14},
    "telegram": {"bot_token": token or None, "chat_id": chat or None},
    "app_overrides": [],
}, indent=2))
PY
    )
    chmod 600 "$CONF_DIR/config.json"
    echo "wrote $CONF_DIR/config.json"
else
    echo "$CONF_DIR/config.json already exists, leaving it untouched"
fi

# -stdin keeps the plaintext password out of the process list, where any local
# user could read it; the umask does the same for the hash on disk.
(
    umask 077
    printf '%s:%s\n' "$VV_AUTH_USER" \
        "$(printf '%s' "$VV_AUTH_PASS" | openssl passwd -apr1 -stdin)" > "$CONF_DIR/htpasswd"
)
chmod 640 "$CONF_DIR/htpasswd"
chown root:www-data "$CONF_DIR/htpasswd" 2>/dev/null || true

VHOST=/etc/nginx/sites-enabled/vps-visibility.conf
if [[ ! -e "$VHOST" ]]; then
    # Render first, write second: nginx includes every file in sites-enabled, so a
    # half-written one would become live config.
    VHOST_CONF=$(sed -e "s|__DOMAIN__|$VV_DOMAIN|g" \
        -e "s|__REPO_DIR__|$REPO_DIR|g" \
        -e "s|__DATA_DIR__|$VV_DATA_DIR|g" \
        "$REPO_DIR/nginx/vhost.conf.template")
    printf '%s\n' "$VHOST_CONF" > "$VHOST"
    if ! nginx -t; then
        # Leaving a rejected vhost behind would break every later nginx reload.
        rm -f "$VHOST"
        echo "nginx rejected the generated vhost, so it was removed again." >&2
        echo "Check the domain you entered: $VV_DOMAIN" >&2
        exit 1
    fi
    systemctl reload nginx
    echo "wrote $VHOST"
else
    echo "$VHOST already exists, leaving it untouched"
fi

printf '*/5 * * * * root python3 %s/collector/collect.py >> /var/log/vps-visibility.log 2>&1\n' \
    "$REPO_DIR" > /etc/cron.d/vps-visibility
chmod 644 /etc/cron.d/vps-visibility

echo "running the collector once..."
python3 "$REPO_DIR/collector/collect.py"

SERVER_IP=$(hostname -I | tr ' ' '\n' \
    | grep -Ev '^$|^10\.|^127\.|^169\.254\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[01])\.|:' \
    | head -1 || true)
echo
if [[ -n "$SERVER_IP" ]]; then
    echo "==> Add this DNS record at your DNS provider now:"
    echo "    A    $VV_DOMAIN    $SERVER_IP"
else
    echo "==> Could not detect a public IPv4 address on this box."
    echo "    Add an A record for $VV_DOMAIN pointing at this server's public IP."
fi
echo

if [[ "${VV_SKIP_TLS:-}" == "1" ]]; then
    echo "VV_SKIP_TLS=1: skipping certbot. Later run: certbot --nginx -d $VV_DOMAIN"
elif [[ -z "$SERVER_IP" ]]; then
    echo "Skipping the DNS wait, there is no detected IP to compare against."
    echo "Once DNS is live, run: certbot --nginx -d $VV_DOMAIN"
else
    prompt VV_CERT_EMAIL "Email for Let's Encrypt expiry notices: "
    echo "waiting for $VV_DOMAIN to resolve to $SERVER_IP (checking every 15s, up to 10 minutes)..."
    RESOLVED=""
    for _ in $(seq 1 40); do
        RESOLVED=$(getent hosts "$VV_DOMAIN" | awk '{print $1}' | head -1 || true)
        [[ "$RESOLVED" == "$SERVER_IP" ]] && break
        sleep 15
    done
    if [[ "$RESOLVED" == "$SERVER_IP" ]] && command -v certbot >/dev/null; then
        certbot --nginx -d "$VV_DOMAIN" --non-interactive --agree-tos -m "$VV_CERT_EMAIL" \
            || echo "certbot failed; fix and rerun: certbot --nginx -d $VV_DOMAIN"
    else
        echo "DNS is not resolving to $SERVER_IP yet (got: ${RESOLVED:-nothing}) or certbot is missing."
        echo "Once DNS is live, run: certbot --nginx -d $VV_DOMAIN"
    fi
fi

echo
echo "Done. Dashboard: https://$VV_DOMAIN (or http:// until certbot has run)"
echo "Data dir: $VV_DATA_DIR   Config: $CONF_DIR/config.json"
