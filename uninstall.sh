#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "uninstall.sh must run as root." >&2
    exit 1
fi

rm -f /etc/cron.d/vps-visibility
rm -f /etc/nginx/sites-enabled/vps-visibility.conf
nginx -t && systemctl reload nginx
echo "Removed the cron entry and nginx vhost."
echo "Left in place: /etc/vps-visibility (config, htpasswd) and the data directory."
echo "Delete those two manually if you want a full removal."
