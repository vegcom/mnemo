#!/usr/bin/env python3
"""Tunnel watchdog — checks all gateway.json tunnels, restarts unhealthy services."""
import json
import os
import subprocess
import urllib.error
import urllib.request

GATEWAY = os.getenv("MNEMO_GATEWAY_JSON", "/etc/mnemo/gateway.json")
LABEL_SERVICES = os.getenv("WATCHDOG_LABEL_SERVICES", "")

gw = json.load(open(GATEWAY))
ls_map = dict(p.split(":", 1) for p in LABEL_SERVICES.split() if ":" in p)

for s in gw.get("servers", []):
    label = s.get("label", "")
    url = s.get("url", "").rstrip("/")
    if label not in ls_map:
        continue
    try:
        urllib.request.urlopen(url, timeout=5)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    if code in (530, 0):
        svc = ls_map[label]
        print(f"unhealthy {url} (HTTP {code}) — restarting {svc}")
        subprocess.run(["systemctl", "--user", "restart", svc])
    else:
        print(f"ok {url} (HTTP {code})")
