#!/usr/bin/env bash
# Called by the systemd timers (see install_schedule.sh). One refresh at a time, with a lock.
#   scheduled_refresh.sh <group>                 # run refresh_and_publish.sh <group>
#   scheduled_refresh.sh --notify-failure <unit> # post a failure message to NOTIFY_WEBHOOK, if set
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HOME/.config/torrent-studio/env"

if [ "${1:-}" = "--notify-failure" ]; then
  unit="${2:-unknown}"
  hook="$(grep -E '^NOTIFY_WEBHOOK=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'")"
  [ -n "$hook" ] || exit 0
  text="Torrent Studio cache refresh FAILED on $(hostname): $unit. See: journalctl -u ${unit%.service} -n 50"
  curl -fsS -m 15 -H 'Content-Type: application/json' \
    -d "$(printf '{"content":"%s","text":"%s"}' "$text" "$text")" "$hook" >/dev/null || true
  exit 0
fi

group="${1:?usage: $0 <group> | --notify-failure <unit>}"
mkdir -p "$HOME/torrent-studio-refresh"
exec 9>"$HOME/torrent-studio-refresh/.refresh.lock"
if ! flock -w 7200 9; then
  echo "Another refresh held the lock for 2 hours; giving up: $group" >&2
  exit 1
fi
echo "[$(date -Is)] starting $group"
"$DIR/refresh_and_publish.sh" "$group"
status=$?
echo "[$(date -Is)] finished $group with status $status"
exit $status
