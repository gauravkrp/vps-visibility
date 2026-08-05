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
    read -rsp "Telegram bot token (enter to skip alerts): " VV_TG_TOKEN; echo
    # It was typed blind, so report the length: enough to catch a truncated
    # paste, without putting any of the token itself in the scrollback.
    if [[ -n "$VV_TG_TOKEN" ]]; then
        echo "read a ${#VV_TG_TOKEN} character token"
    fi
fi
VV_TG_CHAT="${VV_TG_CHAT-}"
if [[ -n "$VV_TG_TOKEN" && -z "$VV_TG_CHAT" ]]; then
    read -rp "Telegram chat id: " VV_TG_CHAT
fi
VV_DATA_DIR="${VV_DATA_DIR:-/var/lib/vps-visibility}"
VV_LOG=/var/log/vps-visibility.log

# The domain is substituted straight into the nginx vhost. Anything outside a
# hostname can close the server block and append directives of its own, and
# nginx would accept the result as valid config, so reject it here rather than
# hope nginx -t notices. Matters most for unattended installs where the value
# comes from a variable instead of a person typing it.
if [[ ! "$VV_DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$ ]] \
   || [[ ${#VV_DOMAIN} -gt 253 ]]; then
    echo "Not a valid domain: '$VV_DOMAIN'" >&2
    echo "Use letters, digits, hyphens and dots only, e.g. vps.example.com" >&2
    exit 1
fi

# sed reads & and \ in a replacement as metacharacters and | is the delimiter
# used below, so a path containing one would silently corrupt the vhost.
sed_replacement() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

mkdir -p "$CONF_DIR" "$VV_DATA_DIR/public/history"
# nginx workers read the htpasswd and the JSON, so these must stay traversable
# whatever umask root happens to run with.
chmod 755 "$CONF_DIR" "$VV_DATA_DIR" "$VV_DATA_DIR/public" "$VV_DATA_DIR/public/history"

if [[ ! -f "$CONF_DIR/config.json" ]]; then
    # The bot token lands in here. The umask keeps it unreadable to everyone but
    # root from the start, including the moment between creation and the chmod.
    # The token and chat id go through the environment, not argv: argv is world
    # readable through ps and /proc/<pid>/cmdline, the environment is not.
    # Write to a temp file and move it into place, so a write that dies partway
    # cannot leave a half-written config that the rerun guard then preserves.
    (
        umask 077
        CONF_TMP=$(mktemp "$CONF_DIR/config.json.XXXXXX")
        if ! VV_TG_TOKEN="$VV_TG_TOKEN" VV_TG_CHAT="$VV_TG_CHAT" \
            python3 - "$VV_DOMAIN" "$VV_DATA_DIR" > "$CONF_TMP" <<'PY'
import json, os, sys
domain, data_dir = sys.argv[1:3]
token, chat = os.environ.get("VV_TG_TOKEN", ""), os.environ.get("VV_TG_CHAT", "")
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
        then
            rm -f "$CONF_TMP"
            echo "failed to write $CONF_DIR/config.json, nothing was left behind" >&2
            exit 1
        fi
        mv "$CONF_TMP" "$CONF_DIR/config.json"
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
    # nginx includes every file in sites-enabled, so nothing lands in there until
    # it is complete: render to a variable, write that to a temp file one
    # directory up, and only then move it in. A write that dies partway (out of
    # space, I/O error) leaves the temp file behind, never live config.
    VHOST_CONF=$(sed -e "s|__DOMAIN__|$(sed_replacement "$VV_DOMAIN")|g" \
        -e "s|__REPO_DIR__|$(sed_replacement "$REPO_DIR")|g" \
        -e "s|__DATA_DIR__|$(sed_replacement "$VV_DATA_DIR")|g" \
        "$REPO_DIR/nginx/vhost.conf.template")
    VHOST_TMP=$(mktemp "$(dirname "$(dirname "$VHOST")")/vps-visibility.conf.XXXXXX")
    if ! printf '%s\n' "$VHOST_CONF" > "$VHOST_TMP"; then
        rm -f "$VHOST_TMP"
        echo "failed to write the vhost, sites-enabled was left untouched." >&2
        exit 1
    fi
    chmod 644 "$VHOST_TMP"
    mv "$VHOST_TMP" "$VHOST"
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

# Create the log before cron does, or cron creates it at root's umask (usually
# world readable) and it then collects five minutes of root stderr forever.
if [[ ! -e "$VV_LOG" ]]; then
    install -m 640 /dev/null "$VV_LOG"
    chown root:adm "$VV_LOG" 2>/dev/null || true
fi

printf '*/5 * * * * root python3 %s/collector/collect.py >> %s 2>&1\n' \
    "$REPO_DIR" "$VV_LOG" > /etc/cron.d/vps-visibility
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
    echo "VV_SKIP_TLS=1: skipping certbot. Later run: certbot --nginx --redirect -d $VV_DOMAIN"
elif [[ -z "$SERVER_IP" ]]; then
    echo "Skipping the DNS wait, there is no detected IP to compare against."
    echo "Once DNS is live, run: certbot --nginx --redirect -d $VV_DOMAIN"
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
        # --redirect: the dashboard is behind basic auth, so plain HTTP would put
        # the credentials on the wire in the clear.
        certbot --nginx --redirect -d "$VV_DOMAIN" --non-interactive --agree-tos -m "$VV_CERT_EMAIL" \
            || echo "certbot failed; fix and rerun: certbot --nginx --redirect -d $VV_DOMAIN"
    else
        echo "DNS is not resolving to $SERVER_IP yet (got: ${RESOLVED:-nothing}) or certbot is missing."
        echo "Once DNS is live, run: certbot --nginx --redirect -d $VV_DOMAIN"
    fi
fi

echo
echo "Done. Dashboard: https://$VV_DOMAIN (or http:// until certbot has run)"
echo "Data dir: $VV_DATA_DIR   Config: $CONF_DIR/config.json"
