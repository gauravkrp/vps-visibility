#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "uninstall.sh must run as root." >&2
    exit 1
fi

rm -f /etc/cron.d/vps-visibility
rm -f /etc/nginx/sites-enabled/vps-visibility.conf
echo "Removed the cron entry and nginx vhost."
echo "Left in place: /etc/vps-visibility (config, htpasswd) and the data directory."
echo "Delete those two manually if you want a full removal."

# Say so loudly if the reload did not happen: until nginx reloads it is still
# serving the dashboard from the config it already has in memory.
if ! nginx -t; then
    echo >&2
    echo "nginx -t failed on the remaining config, so nginx was NOT reloaded." >&2
    echo "The dashboard stays up until it is. Fix the config nginx is complaining" >&2
    echo "about above, then run: systemctl reload nginx" >&2
    exit 1
fi
systemctl reload nginx
echo "Reloaded nginx, the dashboard is no longer served."
