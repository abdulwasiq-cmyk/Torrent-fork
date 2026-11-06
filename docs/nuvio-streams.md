# HD downloads from a self-hosted Nuvio Streams add-on

The movie card's **Download HD** button (quality chips, direct links to the file host) comes from the
[Nuvio Streams add-on](https://github.com/tapframe/NuvioStreamsAddon) (MIT). It is a separate Node service that
runs on the VPS next to this app; the app only calls it. Without `NUVIO_URL` the button never appears.

What to expect (tested on the VPS): about 5-15 s per title, Hollywood titles mostly, Indian titles often nothing.
Files are 2-50 GB HEVC MKV, so the button is *download* only (browsers cannot play them). Only the 4KHDHub
provider worked at the time of writing; the others are dead or blocked from datacenter addresses.

## 1. Run the add-on on the VPS

```
git clone https://github.com/tapframe/NuvioStreamsAddon ~/NuvioStreamsAddon && cd ~/NuvioStreamsAddon
npm install && cp .env.example .env
```

Edit `.env`: set `TMDB_API_KEY=<your key>`. If the VPS cannot reach `api.themoviedb.org` (blocked in India, the
connection is reset) swap the host for `api.tmdb.org` in the add-on's code:

```
grep -rl "api.themoviedb.org" --include=*.js --exclude-dir=node_modules . | xargs sed -i 's#api\.themoviedb\.org#api.tmdb.org#g'
```

The add-on listens on port **7777**. Keep it running across reboots with systemd
(`/etc/systemd/system/nuvio-streams.service`, replace `ubuntu` and the paths if yours differ):

```
[Unit]
Description=Nuvio Streams add-on
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/NuvioStreamsAddon
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```
sudo systemctl daemon-reload && sudo systemctl enable --now nuvio-streams
curl -s localhost:7777/stream/movie/tmdb:278.json | head -c 300     # the route needs the .json suffix
```

Do not expose port 7777 to the internet: keep it closed in the Oracle security list and firewall.

## 2. Point the app at it

The app runs in Docker, so `localhost` inside the container is not the VPS. `docker-compose.yml` therefore already
sets `NUVIO_URL` to `http://host.docker.internal:7777` and maps `host.docker.internal` to the VPS
(`extra_hosts`). After a deploy nothing more is needed; set `NUVIO_URL=` (empty) in the VPS `.env` to switch the
button off. Check the container can reach the add-on:
`docker exec torrent-studio python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:7777/', timeout=5).status)"`.

On Render leave `NUVIO_URL` unset (no button), or point it at a public address of the add-on that you have protected.

## How the app uses it

`GET /api/nuvio/streams?tmdb_id=<id>` (called once when a movie card opens, never by page loads or paging)
asks the add-on for `/stream/movie/tmdb:<id>.json`, keeps up to 12 options (best quality first), caches a
good answer for 20 minutes and an empty one for 10, and shares one scrape between simultaneous clicks.
Links are https only and percent-encoded; the browser downloads straight from the file host (no VPS bandwidth).
Never check these links with a HEAD request: the file host answers 403 to HEAD but serves GET and range requests.
