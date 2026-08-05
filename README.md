# vps-visibility

One dashboard for a hand-rolled VPS: every nginx vhost mapped to the app
actually serving it (Docker, PM2, or bare process), with per-app memory,
disk, uptime, HTTPS health, cert expiry, and Telegram alerts when
something breaks. Zero runtime dependencies: Python 3 stdlib + one static
HTML page. Full docs land with the first release.
