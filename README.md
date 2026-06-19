# macmonitor

A tiny macOS **menu bar** system monitor. Shows realtime **CPU %**, **RAM used**,
and **network link speed** in the menu bar title; **disk I/O**, **live network
up/down**, an on-demand **fast.com-style speed test**, and an **auto-start**
toggle in the dropdown.

Menu bar title: `CPU 23% · RAM 8.1G · Wi-Fi 1200M`
(the last segment shows the network link speed, or `Net --` when it can't be read)

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python macmonitor.py
```

A menu bar item appears. Click it for the CPU / RAM / network / disk dropdown,
the speed test, and the auto-start toggle.

## Build a .app

```bash
.venv/bin/pip install py2app
.venv/bin/python setup.py py2app
```

This produces `dist/macmonitor.app`.

### Make it launch by double-click (Gatekeeper)

The built app is **unsigned**, so macOS Gatekeeper blocks it on first launch.
Two ways to allow it:

1. **Ad-hoc sign it** (recommended — silences Gatekeeper for local use):
   ```bash
   codesign --force --deep --sign - dist/macmonitor.app
   ```
2. Or the first time you open it: **right-click the app → Open**, then confirm
   in the dialog. (Double-clicking directly may just show a warning and refuse.)

Then drag `dist/macmonitor.app` into `/Applications` to install.

## Auto-start at login

Use the **开机自启** item in the dropdown to toggle it. It installs/removes a
LaunchAgent at `~/Library/LaunchAgents/com.macmonitor.plist` that opens
`/Applications/macmonitor.app` at login. Install the app in `/Applications`
first so the toggle points at the right place.

## What the numbers mean

- **Link speed** (title) = your Wi-Fi/Ethernet *negotiated* rate, not actual usage.
- **网络 下载 / 上传** (dropdown) = current real throughput right now.
- **⚡ 立即测速** = actively measures real achievable speed via Cloudflare's speed
  endpoints (uses some data; on-demand only, never automatic). Besides download
  and upload, it reports **延迟 (latency)** and **抖动 (jitter)**, **负载延迟
  (loaded latency)** measured during the down/up transfers, a heuristic **网络
  质量 (network quality)** rating for video/gaming/chat, and the **服务器 /
  网络 / IP** info (edge colo & city, your ISP/ASN and public IP) from
  Cloudflare's `/meta` endpoint. Packet loss is not measured — that requires
  WebRTC/UDP, which a plain HTTP client can't do.

## Tests

```bash
.venv/bin/python -m pytest -v
```
