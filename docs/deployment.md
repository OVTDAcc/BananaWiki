# Deployment Guide

This guide covers all the ways to run BananaWiki in production.

## Contents

- [Automated setup wizard](#automated-setup-wizard)
- [systemd (recommended)](#systemd-recommended)
- [Manual Gunicorn](#manual-gunicorn)
- [Cloudflare (custom domain + free SSL)](#cloudflare-custom-domain--free-ssl)
- [Nginx reverse proxy](#nginx-reverse-proxy)
- [Caddy reverse proxy](#caddy-reverse-proxy)
- [IP-only access (no domain)](#ip-only-access-no-domain)
- [Multiple apps on one server](#multiple-apps-on-one-server)

---

## Automated setup wizard

`setup.py` is a self-contained, one-shot provisioning tool. Run it on the server before starting BananaWiki for the first time and it will:

1. Detect your server's public IP (and optional IPv6)
2. Ask for your service name, domain, worker count, and port
3. Verify DNS resolution for your domain
4. Create and enable a **systemd** service unit
5. Write an **nginx** reverse-proxy config (with HTTP → HTTPS redirect)
6. Optionally run **Certbot** to obtain a Let's Encrypt TLS certificate

```bash
python setup.py              # binds to 127.0.0.1:5050 by default
python setup.py --host 0.0.0.0 --port 5050   # to reach it from another machine
```

Open the printed URL in a browser and follow the three-phase wizard. The wizard shuts itself down automatically when provisioning is complete.

> `setup.py` requires root privileges for writing systemd and nginx files. Run it as `sudo python setup.py` or from a root shell.

---

## systemd (recommended)

A systemd service keeps BananaWiki running continuously and restarts it automatically after crashes or reboots.

**1. Install and set up the venv:**
```bash
sudo mkdir -p /opt/BananaWiki
sudo chown www-data:www-data /opt/BananaWiki
cd /opt/BananaWiki
git clone https://github.com/ovtdadt/BananaWiki.git .
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Edit `config.py`:**
```python
PORT = 5001
PROXY_MODE = True              # True when behind nginx or Cloudflare
```

**3. Install and start the service:**
```bash
sudo cp bananawiki.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bananawiki    # start on boot
sudo systemctl start bananawiki     # start now
```

**Service management:**
```bash
sudo systemctl status bananawiki    # check status
sudo systemctl restart bananawiki   # restart after config changes
sudo systemctl stop bananawiki      # stop
journalctl -u bananawiki -f         # follow live logs
```

> **Tip:** Open `bananawiki.service` and update `User`, `Group`, and `WorkingDirectory` if your setup path or user is different from the defaults.

---

## Manual Gunicorn

Without systemd, start Gunicorn directly:

```bash
source venv/bin/activate
gunicorn wsgi:app -c gunicorn.conf.py
```

Or with explicit options:
```bash
gunicorn wsgi:app --bind 0.0.0.0:5001 --workers 2
```

`gunicorn.conf.py` reads `HOST`, `PORT`, and `PROXY_MODE` from `config.py` automatically.

---

## Cloudflare (custom domain + free SSL)

Cloudflare is the easiest way to get a real domain and HTTPS in front of BananaWiki.

**1.** Add your domain to Cloudflare and point your registrar's nameservers at Cloudflare.

**2.** Create a DNS A record:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| `A` | `wiki` | `YOUR_SERVER_IP` | Proxied (orange cloud) |

**3.** Set Cloudflare's SSL/TLS mode to **Flexible** (Cloudflare ↔ browser is HTTPS; Cloudflare ↔ your server is HTTP).

> For higher security, use **Full** or **Full (Strict)** mode with a certificate on your server.

**4.** Set `config.py`:
```python
PORT = 5001
HOST = "0.0.0.0"           # Cloudflare connects directly to your IP
PROXY_MODE = True
```

**Recommended Cloudflare settings:**
- Always Use HTTPS: On
- Minimum TLS Version: TLS 1.2
- Automatic HTTPS Rewrites: On

---

## Nginx reverse proxy

Use nginx when you want to run multiple apps on the same server, or terminate TLS yourself.

**`/etc/nginx/sites-available/bananawiki`:**
```nginx
server {
    listen 443 ssl;
    server_name wiki.example.com;

    ssl_certificate     /etc/letsencrypt/live/wiki.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/wiki.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name wiki.example.com;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/bananawiki /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**`config.py`:**
```python
PORT = 5001
PROXY_MODE = True
```

---

## Caddy reverse proxy

Caddy handles TLS certificates automatically via Let's Encrypt.

**`Caddyfile`:**
```
wiki.example.com {
    reverse_proxy 127.0.0.1:5001
}
```

**`config.py`:**
```python
PORT = 5001
PROXY_MODE = True
```

---

## IP-only access (no domain)

No DNS setup required. Just set `HOST = "0.0.0.0"` in `config.py`:

```python
PORT = 5001
HOST = "0.0.0.0"
```

Access at `http://<your-server-ip>:5001`.

> Setting `HOST = "0.0.0.0"` exposes the port to all network interfaces. Make sure your firewall only allows traffic from trusted sources.

---

## Multiple apps on one server

Each app needs its own port. Set `PORT` in each app's `config.py`:

| App | Port | Domain |
|---|---|---|
| BananaWiki | 5001 | `wiki.example.com` |
| Another app | 5002 | `app.example.com` |

Set up nginx or Cloudflare to route each domain to the right port. Each app runs its own Gunicorn process and systemd service.
