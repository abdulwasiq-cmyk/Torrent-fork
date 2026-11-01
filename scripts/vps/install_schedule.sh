#!/usr/bin/env bash
# Install (or update) the automatic cache refresh on the VPS using systemd timers.
#
#   bash scripts/vps/install_schedule.sh              # install / update
#   bash scripts/vps/install_schedule.sh --remove     # remove the timers
#
# What runs, as the current user (nothing opens a port; the VPS only makes outbound calls):
#   weekly  Monday 03:00     refresh_and_publish.sh hollywood-bollywood
#   monthly 1st      04:00   refresh_and_publish.sh franchise     (Marvel, DC and classics)
# Each run refreshes the data, publishes one bundle and triggers a Render deploy, exactly like running
# the script by hand. A missed run (VPS was off) happens at next boot. Runs never overlap (flock).
#
# Optional: put NOTIFY_WEBHOOK=<Discord/Slack-style webhook URL> in ~/.config/torrent-studio/env
# to get a message when a run fails.
# Override times with WEEKLY_AT / MONTHLY_AT (systemd OnCalendar syntax), e.g.
#   WEEKLY_AT="Sun *-*-* 02:00:00" bash scripts/vps/install_schedule.sh
set -euo pipefail

WEEKLY_AT="${WEEKLY_AT:-Mon *-*-* 03:00:00}"
MONTHLY_AT="${MONTHLY_AT:-*-*-01 04:00:00}"
RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/scheduled_refresh.sh"
UNIT_DIR=/etc/systemd/system
NAMES=(weekly monthly)

if [ "${1:-}" = "--remove" ]; then
  for n in "${NAMES[@]}"; do
    sudo systemctl disable --now "torrent-studio-refresh-$n.timer" 2>/dev/null || true
    sudo rm -f "$UNIT_DIR/torrent-studio-refresh-$n.timer" "$UNIT_DIR/torrent-studio-refresh-$n.service"
  done
  sudo rm -f "$UNIT_DIR/torrent-studio-refresh-failed@.service"
  sudo systemctl daemon-reload
  echo "Removed."
  exit 0
fi

command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }
command -v flock >/dev/null || { echo "flock is required (apt-get install util-linux)"; exit 1; }
[ -f "$RUN_HOME/.config/torrent-studio/env" ] || { echo "Missing $RUN_HOME/.config/torrent-studio/env (see backend/cache-seed/README.md)"; exit 1; }
chmod +x "$RUNNER" "$SCRIPT_DIR/refresh_and_publish.sh"

write_service() { # name group
  sudo tee "$UNIT_DIR/torrent-studio-refresh-$1.service" >/dev/null <<UNIT
[Unit]
Description=Torrent Studio cache refresh ($2)
After=network-online.target
Wants=network-online.target
OnFailure=torrent-studio-refresh-failed@%n.service

[Service]
Type=oneshot
User=$RUN_USER
Environment=HOME=$RUN_HOME
ExecStart=$RUNNER $2
TimeoutStartSec=6h
Nice=10
UNIT
}

write_timer() { # name calendar
  sudo tee "$UNIT_DIR/torrent-studio-refresh-$1.timer" >/dev/null <<UNIT
[Unit]
Description=Torrent Studio cache refresh timer ($1)

[Timer]
OnCalendar=$2
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
UNIT
}

write_service weekly hollywood-bollywood
write_service monthly franchise
write_timer weekly "$WEEKLY_AT"
write_timer monthly "$MONTHLY_AT"

sudo tee "$UNIT_DIR/torrent-studio-refresh-failed@.service" >/dev/null <<UNIT
[Unit]
Description=Report a failed Torrent Studio refresh (%i)

[Service]
Type=oneshot
User=$RUN_USER
Environment=HOME=$RUN_HOME
ExecStart=$RUNNER --notify-failure %i
UNIT

sudo systemctl daemon-reload
for n in "${NAMES[@]}"; do sudo systemctl enable --now "torrent-studio-refresh-$n.timer"; done

echo
systemctl list-timers 'torrent-studio-refresh-*' --no-pager
echo
echo "Run one now:   sudo systemctl start torrent-studio-refresh-weekly.service   (follow: journalctl -fu torrent-studio-refresh-weekly)"
echo "Last results:  journalctl -u 'torrent-studio-refresh-*' --since '7 days ago' | tail -50"
