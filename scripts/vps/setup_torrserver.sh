#!/usr/bin/env bash
# One-paste TorrServer setup behind Caddy, for the Torrent Studio "Engine Lab".
# Usage:  DOMAIN=ts.example.com bash scripts/vps/setup_torrserver.sh
# Needs: Docker, Caddy (see the Caddy setup), and a DNS A record for $DOMAIN.
set -euo pipefail

DOMAIN="${DOMAIN:?Set DOMAIN, e.g. DOMAIN=ts.example.com}"
PORT="${TS_PORT:-8090}"
DATA_DIR="${TS_DATA_DIR:-/opt/torrserver}"
KEY_FILE=/etc/torrserver.key
CADDYFILE=/etc/caddy/Caddyfile

command -v docker >/dev/null || { echo "Docker is not installed"; exit 1; }
command -v caddy >/dev/null || { echo "Caddy is not installed"; exit 1; }

sudo mkdir -p "$DATA_DIR"
if [ ! -s "$KEY_FILE" ]; then
  head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32 | sudo tee "$KEY_FILE" >/dev/null
  sudo chmod 600 "$KEY_FILE"
fi
KEY="$(sudo cat "$KEY_FILE")"

sudo docker rm -f torrserver >/dev/null 2>&1 || true
sudo docker run -d --name torrserver --restart unless-stopped \
  -p 127.0.0.1:${PORT}:8090 \
  -v "$DATA_DIR":/opt/ts/config \
  ghcr.io/yourok/torrserver:latest >/dev/null

# Replace any previous TorrServer block, then append a fresh one.
sudo touch "$CADDYFILE"
sudo python3 - "$CADDYFILE" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
text = re.sub(r"\n?# BEGIN torrserver.*?# END torrserver\n?", "\n", text, flags=re.S)
open(path, "w").write(text)
PY
sudo tee -a "$CADDYFILE" >/dev/null <<CADDY
# BEGIN torrserver
$DOMAIN {
    encode zstd gzip
    @denied {
        not method OPTIONS
        not query key=$KEY
    }
    respond @denied "forbidden" 403
    reverse_proxy 127.0.0.1:$PORT {
        flush_interval -1
        transport http {
            read_timeout 30m
        }
    }
}
# END torrserver
CADDY

sudo caddy validate --config "$CADDYFILE"
sudo systemctl reload caddy
command -v ufw >/dev/null && sudo ufw status | grep -q active && sudo ufw allow 80,443/tcp || true

sleep 4
echo
echo "TorrServer URL : https://$DOMAIN"
echo "Access key     : $KEY"
echo "Check          : curl -s \"https://$DOMAIN/echo?key=$KEY\""
echo "Open the lab   : <your frontend>/?lab=engines"
