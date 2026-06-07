# macmonitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A macOS menu bar app named `macmonitor` that shows realtime CPU %, RAM used, and network link speed in the title, with disk I/O, live network up/down, an on-demand fast.com-style speed test, and an auto-launch toggle in the dropdown.

**Architecture:** Pure, testable logic lives in `metrics.py` (sampling, rate math, human-readable formatting, link-speed parsing, speed test) and `autostart.py` (LaunchAgent plist generation + load/unload). `macmonitor.py` is thin rumps UI glue: a `rumps.App` subclass with a 2-second timer that calls the pure functions and updates the title/menu. py2app packages it; a LaunchAgent plist provides auto-start.

**Tech Stack:** Python 3, rumps (menu bar), psutil (system metrics), Cloudflare speed endpoints + urllib (speed test), system_profiler/ifconfig (link speed), py2app (packaging), launchd (auto-start).

---

## File Structure

- `metrics.py` — pure functions: format helpers, rate calculation, CPU/RAM/net/disk sampling, link-speed read, speed test. No rumps imports.
- `autostart.py` — plist path constant, plist XML generation, install/uninstall via `launchctl`, `is_enabled()`.
- `macmonitor.py` — `MacMonitor(rumps.App)`: builds menu, 2s timer updates title + menu, wires speed-test button (background thread) and auto-start toggle.
- `requirements.txt` — runtime deps.
- `setup.py` — py2app config (LSUIElement agent app).
- `README.md` — run / package / autostart instructions.
- `tests/test_metrics.py`, `tests/test_autostart.py` — unit tests for pure logic.

Spec: `docs/superpowers/specs/2026-06-07-macmonitor-design.md`

---

## Task 1: Project scaffolding & dependencies

**Files:**
- Create: `requirements.txt`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write requirements.txt**

```
rumps==0.4.0
psutil==6.1.0
```

- [ ] **Step 2: Create empty tests package marker**

Create `tests/__init__.py` with empty content.

- [ ] **Step 3: Create virtualenv and install deps + pytest**

Run:
```bash
cd ~/macmonitor
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt pytest
echo '.venv/' >> .gitignore
```
Expected: installs succeed; `rumps` and `psutil` import without error.

- [ ] **Step 4: Verify imports**

Run: `.venv/bin/python -c "import rumps, psutil; print('ok')"`
Expected: prints `ok`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/__init__.py .gitignore
git commit -m "chore: scaffold macmonitor deps and tests package"
```

---

## Task 2: Human-readable byte/rate formatting

**Files:**
- Create: `metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics.py
import metrics


def test_fmt_rate_below_one_mb_shows_kb():
    # 820 KB/s -> "820K"
    assert metrics.fmt_rate(820 * 1024) == "820K"


def test_fmt_rate_at_or_above_one_mb_shows_mb_one_decimal():
    # 1.2 MB/s -> "1.2M"
    assert metrics.fmt_rate(int(1.2 * 1024 * 1024)) == "1.2M"


def test_fmt_rate_zero():
    assert metrics.fmt_rate(0) == "0K"


def test_fmt_gb_one_decimal():
    # 8.1 GiB
    assert metrics.fmt_gb(int(8.1 * 1024**3)) == "8.1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `AttributeError: module 'metrics' has no attribute 'fmt_rate'`

- [ ] **Step 3: Write minimal implementation**

```python
# metrics.py
"""Pure, testable system-metric helpers for macmonitor. No rumps imports."""

_KB = 1024
_MB = 1024 ** 2
_GB = 1024 ** 3


def fmt_rate(bytes_per_sec: float) -> str:
    """Bytes/sec -> compact string. <1 MB/s shows KB ('820K'), else MB ('1.2M')."""
    if bytes_per_sec >= _MB:
        return f"{bytes_per_sec / _MB:.1f}M"
    return f"{int(bytes_per_sec / _KB)}K"


def fmt_gb(num_bytes: float) -> str:
    """Bytes -> GiB with one decimal, no unit suffix (e.g. '8.1')."""
    return f"{num_bytes / _GB:.1f}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: add human-readable rate/size formatting"
```

---

## Task 3: Rate calculator (counter delta over time)

**Files:**
- Modify: `metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_metrics.py

def test_rate_calc_first_sample_returns_zero():
    rc = metrics.RateCalc()
    # first observation has no previous frame
    assert rc.update(read=1000, write=2000, now=10.0) == (0.0, 0.0)


def test_rate_calc_second_sample_divides_by_interval():
    rc = metrics.RateCalc()
    rc.update(read=1000, write=2000, now=10.0)
    # 1 second later: +500 read, +1000 write
    assert rc.update(read=1500, write=3000, now=11.0) == (500.0, 1000.0)


def test_rate_calc_handles_zero_interval():
    rc = metrics.RateCalc()
    rc.update(read=1000, write=2000, now=10.0)
    # same timestamp -> avoid divide-by-zero, return 0
    assert rc.update(read=1500, write=3000, now=10.0) == (0.0, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k rate_calc -v`
Expected: FAIL — `AttributeError: module 'metrics' has no attribute 'RateCalc'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to metrics.py

class RateCalc:
    """Turns monotonically increasing byte counters into per-second rates.

    Generic over two channels (read/write or recv/sent). Returns (0.0, 0.0)
    on the first sample and on a non-positive time interval.
    """

    def __init__(self):
        self._prev_read = None
        self._prev_write = None
        self._prev_t = None

    def update(self, read: int, write: int, now: float):
        if self._prev_t is None or now <= self._prev_t:
            rate = (0.0, 0.0)
        else:
            dt = now - self._prev_t
            rate = ((read - self._prev_read) / dt, (write - self._prev_write) / dt)
        # On a zero/negative interval we keep the previous baseline so the next
        # valid sample still measures from the correct point.
        if self._prev_t is None or now > self._prev_t:
            self._prev_read, self._prev_write, self._prev_t = read, write, now
        return rate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k rate_calc -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: add RateCalc for counter-to-rate conversion"
```

---

## Task 4: Live sampling functions (CPU, RAM, net, disk)

**Files:**
- Modify: `metrics.py`
- Test: `tests/test_metrics.py`

These wrap psutil. We test the shape/keys of the returned dict (not exact values, which vary by machine).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_metrics.py

def test_sample_cpu_ram_returns_expected_keys():
    s = metrics.sample_cpu_ram()
    assert set(s.keys()) == {"cpu_pct", "ram_used", "ram_total", "ram_pct"}
    assert 0.0 <= s["cpu_pct"] <= 100.0 * (psutil_cpu_count() or 1)
    assert s["ram_used"] <= s["ram_total"]


def test_raw_net_counters_returns_two_ints():
    recv, sent = metrics.raw_net_counters()
    assert isinstance(recv, int) and isinstance(sent, int)
    assert recv >= 0 and sent >= 0


def test_raw_disk_counters_returns_two_ints():
    read, write = metrics.raw_disk_counters()
    assert isinstance(read, int) and isinstance(write, int)
    assert read >= 0 and write >= 0


def psutil_cpu_count():
    import psutil
    return psutil.cpu_count()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k "sample or counters" -v`
Expected: FAIL — `AttributeError: module 'metrics' has no attribute 'sample_cpu_ram'`

- [ ] **Step 3: Write minimal implementation**

```python
# add near top of metrics.py, after the unit constants
import psutil

# Prime psutil's cpu_percent so the first real call returns a meaningful value
# (the very first call always returns 0.0 by design).
psutil.cpu_percent(interval=None)


# append to metrics.py

def sample_cpu_ram() -> dict:
    """Snapshot CPU percent (since last call) and RAM usage."""
    vm = psutil.virtual_memory()
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used": vm.used,
        "ram_total": vm.total,
        "ram_pct": vm.percent,
    }


def raw_net_counters() -> tuple:
    """(bytes_recv, bytes_sent) summed across all interfaces."""
    n = psutil.net_io_counters()
    return n.bytes_recv, n.bytes_sent


def raw_disk_counters() -> tuple:
    """(read_bytes, write_bytes) summed across all disks. (0, 0) if unavailable."""
    d = psutil.disk_io_counters()
    if d is None:
        return 0, 0
    return d.read_bytes, d.write_bytes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k "sample or counters" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: add psutil sampling for cpu/ram/net/disk"
```

---

## Task 5: Wi-Fi / Ethernet link-speed reader

**Files:**
- Modify: `metrics.py`
- Test: `tests/test_metrics.py`

`read_link_speed()` shells out to `system_profiler` (slow), so it is split into a pure parser (`parse_airport_tx_rate`) that we unit-test, plus a thin caller we verify only doesn't crash.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_metrics.py

SP_SAMPLE = """
      Interfaces:
        en0:
          Card Type: Wi-Fi
          Status: Connected
          Current Network Information:
            MyNetwork:
              PHY Mode: 802.11ax
              Channel: 36 (5GHz, 80MHz)
              Tx Rate: 1200
"""


def test_parse_airport_tx_rate_extracts_mbps():
    assert metrics.parse_airport_tx_rate(SP_SAMPLE) == 1200


def test_parse_airport_tx_rate_missing_returns_none():
    assert metrics.parse_airport_tx_rate("no rate here") is None


def test_read_link_speed_does_not_crash():
    # On CI/headless this may be None; we only require it not to raise.
    result = metrics.read_link_speed()
    assert result is None or isinstance(result, str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k "link or airport" -v`
Expected: FAIL — `AttributeError: module 'metrics' has no attribute 'parse_airport_tx_rate'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to imports section of metrics.py
import re
import subprocess

# append to metrics.py

def parse_airport_tx_rate(sp_output: str):
    """Extract the 'Tx Rate' (Mbps int) from `system_profiler SPAirPortDataType`."""
    m = re.search(r"Tx Rate:\s*([0-9]+)", sp_output)
    return int(m.group(1)) if m else None


def read_link_speed():
    """Return a short label like 'Wi-Fi 1200M', or None if unavailable.

    Tries Wi-Fi Tx Rate first (system_profiler). Best-effort; never raises.
    """
    try:
        out = subprocess.run(
            ["system_profiler", "SPAirPortDataType"],
            capture_output=True, text=True, timeout=8,
        ).stdout
        rate = parse_airport_tx_rate(out)
        if rate:
            return f"Wi-Fi {rate}M"
    except Exception:
        pass
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k "link or airport" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: add Wi-Fi link-speed reader with testable parser"
```

---

## Task 6: On-demand fast.com-style speed test

**Files:**
- Modify: `metrics.py`
- Test: `tests/test_metrics.py`

The HTTP calls are isolated behind a tiny seam (`_http_download_bytes` / `_http_upload_bytes`) so `run_speed_test` can be tested with fakes — no real network in the unit test.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_metrics.py

def test_mbps_from_bytes_and_time():
    # 12.5 MB in 1.0s = 100 Mbps
    assert metrics.mbps(12_500_000, 1.0) == 100.0


def test_run_speed_test_uses_injected_io(monkeypatch):
    # Fake: 25 MB downloaded in 2s, 5 MB uploaded in 1s
    monkeypatch.setattr(metrics, "_http_download_bytes", lambda nbytes, t: (25_000_000, 2.0))
    monkeypatch.setattr(metrics, "_http_upload_bytes", lambda nbytes, t: (5_000_000, 1.0))
    result = metrics.run_speed_test()
    assert result["ok"] is True
    assert result["down_mbps"] == 100.0
    assert result["up_mbps"] == 40.0


def test_run_speed_test_failure_returns_not_ok(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(metrics, "_http_download_bytes", boom)
    result = metrics.run_speed_test()
    assert result["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k "mbps or speed_test" -v`
Expected: FAIL — `AttributeError: module 'metrics' has no attribute 'mbps'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to imports section of metrics.py
import time
import urllib.request

# append to metrics.py

_DOWN_URL = "https://speed.cloudflare.com/__down?bytes={n}"
_UP_URL = "https://speed.cloudflare.com/__up"
_DOWN_BYTES = 25_000_000
_UP_BYTES = 10_000_000


def mbps(num_bytes: float, seconds: float) -> float:
    """Bytes transferred over `seconds` -> megabits per second, 1 decimal."""
    if seconds <= 0:
        return 0.0
    return round((num_bytes * 8) / seconds / 1_000_000, 1)


def _http_download_bytes(nbytes: int, timeout: float):
    """Download nbytes from Cloudflare; return (bytes_read, elapsed_seconds)."""
    req = urllib.request.Request(_DOWN_URL.format(n=nbytes))
    start = time.monotonic()
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
    return total, time.monotonic() - start


def _http_upload_bytes(nbytes: int, timeout: float):
    """Upload nbytes to Cloudflare; return (bytes_sent, elapsed_seconds)."""
    payload = b"\0" * nbytes
    req = urllib.request.Request(_UP_URL, data=payload, method="POST")
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()
    return nbytes, time.monotonic() - start


def run_speed_test() -> dict:
    """Blocking fast.com-style test. Returns dict with ok/down_mbps/up_mbps."""
    try:
        dn_bytes, dn_t = _http_download_bytes(_DOWN_BYTES, timeout=30)
        up_bytes, up_t = _http_upload_bytes(_UP_BYTES, timeout=30)
        return {
            "ok": True,
            "down_mbps": mbps(dn_bytes, dn_t),
            "up_mbps": mbps(up_bytes, up_t),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -k "mbps or speed_test" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full metrics suite**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: add on-demand fast.com-style speed test"
```

---

## Task 7: Auto-start (LaunchAgent plist) module

**Files:**
- Create: `autostart.py`
- Test: `tests/test_autostart.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autostart.py
import plistlib
import autostart


def test_plist_path_is_in_launchagents():
    p = autostart.plist_path()
    assert p.name == "com.macmonitor.plist"
    assert "LaunchAgents" in str(p)


def test_build_plist_bytes_is_valid_and_runs_target():
    data = autostart.build_plist_bytes("/Applications/macmonitor.app")
    parsed = plistlib.loads(data)
    assert parsed["Label"] == "com.macmonitor"
    assert parsed["RunAtLoad"] is True
    # the program arguments should reference the target
    assert any("macmonitor" in str(a) for a in parsed["ProgramArguments"])


def test_is_enabled_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "plist_path", lambda: tmp_path / "com.macmonitor.plist")
    assert autostart.is_enabled() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_autostart.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autostart'`

- [ ] **Step 3: Write minimal implementation**

```python
# autostart.py
"""macmonitor auto-start via a per-user launchd LaunchAgent."""
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.macmonitor"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist_bytes(app_path: str) -> bytes:
    """Build LaunchAgent plist bytes that open the given .app at login."""
    spec = {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/open", "-a", app_path],
        "RunAtLoad": True,
    }
    return plistlib.dumps(spec)


def is_enabled() -> bool:
    return plist_path().exists()


def enable(app_path: str) -> None:
    """Write the plist and load it into launchd."""
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(build_plist_bytes(app_path))
    subprocess.run(["launchctl", "load", str(p)], capture_output=True)


def disable() -> None:
    """Unload and remove the plist."""
    p = plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        p.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_autostart.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autostart.py tests/test_autostart.py
git commit -m "feat: add launchd auto-start install/uninstall module"
```

---

## Task 8: rumps menu bar app (UI glue)

**Files:**
- Create: `macmonitor.py`

This is UI glue — verified manually, not unit-tested. It wires the pure functions into a `rumps.App` with a 2-second timer, a background-threaded speed test, and the auto-start toggle.

- [ ] **Step 1: Write the app**

```python
# macmonitor.py
"""macmonitor — a macOS menu bar system monitor."""
import sys
import threading
import time

import rumps

import metrics
import autostart

APP_PATH = "/Applications/macmonitor.app"  # used by the auto-start LaunchAgent
LINK_SPEED_REFRESH_SECS = 30


class MacMonitor(rumps.App):
    def __init__(self):
        super().__init__("macmonitor", title="macmonitor …", quit_button=None)

        # menu items (kept as attributes so the timer can mutate their titles)
        self.cpu_item = rumps.MenuItem("CPU 使用率  —")
        self.ram_item = rumps.MenuItem("RAM 已用  —")
        self.net_down_item = rumps.MenuItem("网络 下载  —")
        self.net_up_item = rumps.MenuItem("网络 上传  —")
        self.link_item = rumps.MenuItem("连接速率  —")
        self.disk_read_item = rumps.MenuItem("磁盘 读取  —")
        self.disk_write_item = rumps.MenuItem("磁盘 写入  —")
        self.speedtest_item = rumps.MenuItem("⚡ 立即测速 (fast.com 式)", callback=self.on_speed_test)
        self.speedtest_result = rumps.MenuItem("上次结果: 未测试")
        self.autostart_item = rumps.MenuItem("开机自启", callback=self.on_toggle_autostart)
        self.autostart_item.state = 1 if autostart.is_enabled() else 0

        self.menu = [
            self.cpu_item,
            None,
            self.ram_item,
            None,
            self.net_down_item,
            self.net_up_item,
            self.link_item,
            None,
            self.disk_read_item,
            self.disk_write_item,
            None,
            self.speedtest_item,
            self.speedtest_result,
            None,
            self.autostart_item,
            rumps.MenuItem("退出", callback=rumps.quit_application),
        ]

        self._net_rate = metrics.RateCalc()
        self._disk_rate = metrics.RateCalc()
        self._link_label = None
        self._last_link_read = 0.0
        self._speedtest_running = False

    @rumps.timer(2)
    def refresh(self, _):
        now = time.monotonic()
        s = metrics.sample_cpu_ram()

        recv, sent = metrics.raw_net_counters()
        dn, up = self._net_rate.update(recv, sent, now)
        read, write = metrics.raw_disk_counters()
        rd, wr = self._disk_rate.update(read, write, now)

        # link speed is slow to read; refresh at most every 30s
        if now - self._last_link_read > LINK_SPEED_REFRESH_SECS or self._link_label is None:
            self._link_label = metrics.read_link_speed()
            self._last_link_read = now
        link_title = self._link_label or "Net --"

        # menu bar title: CPU · RAM · link speed
        self.title = (
            f"CPU {s['cpu_pct']:.0f}% · "
            f"RAM {metrics.fmt_gb(s['ram_used'])}G · "
            f"{link_title}"
        )

        # dropdown detail
        self.cpu_item.title = f"CPU 使用率  {s['cpu_pct']:.1f}%"
        self.ram_item.title = (
            f"RAM 已用  {metrics.fmt_gb(s['ram_used'])} GB / "
            f"{metrics.fmt_gb(s['ram_total'])} GB ({s['ram_pct']:.0f}%)"
        )
        self.net_down_item.title = f"网络 下载  {metrics.fmt_rate(dn)}/s"
        self.net_up_item.title = f"网络 上传  {metrics.fmt_rate(up)}/s"
        self.link_item.title = f"连接速率  {self._link_label or '--'}"
        self.disk_read_item.title = f"磁盘 读取  {metrics.fmt_rate(rd)}/s"
        self.disk_write_item.title = f"磁盘 写入  {metrics.fmt_rate(wr)}/s"

    def on_speed_test(self, _):
        if self._speedtest_running:
            return
        self._speedtest_running = True
        self.speedtest_result.title = "测速中…"

        def worker():
            result = metrics.run_speed_test()
            if result["ok"]:
                self.speedtest_result.title = (
                    f"上次结果: ↓{result['down_mbps']} / ↑{result['up_mbps']} Mbps"
                )
            else:
                self.speedtest_result.title = "测速失败（检查网络）"
            self._speedtest_running = False

        threading.Thread(target=worker, daemon=True).start()

    def on_toggle_autostart(self, sender):
        try:
            if sender.state:
                autostart.disable()
                sender.state = 0
            else:
                autostart.enable(APP_PATH)
                sender.state = 1
        except Exception as e:
            rumps.alert("开机自启设置失败", str(e))


if __name__ == "__main__":
    MacMonitor().run()
```

- [ ] **Step 2: Run the app manually**

Run: `.venv/bin/python macmonitor.py`
Expected: a menu bar item appears showing `CPU x% · RAM y.yG · Wi-Fi …` (or `Net --`). Open the dropdown — all rows populate within ~2s. Numbers move when you load the machine. Quit via the menu's 退出.

- [ ] **Step 3: Verify the speed test**

Click `⚡ 立即测速`. The result row shows `测速中…` then `↓.. / ↑.. Mbps` within ~10s. Compare magnitude to fast.com — same ballpark.

- [ ] **Step 4: Verify auto-start toggle**

Click 开机自启 on → confirm `~/Library/LaunchAgents/com.macmonitor.plist` exists:
```bash
ls ~/Library/LaunchAgents/com.macmonitor.plist
```
Click it off → confirm the file is gone. (The app at `/Applications/macmonitor.app` need not exist yet for the toggle/file test.)

- [ ] **Step 5: Commit**

```bash
git add macmonitor.py
git commit -m "feat: add rumps menu bar UI wiring"
```

---

## Task 9: py2app packaging

**Files:**
- Create: `setup.py`

- [ ] **Step 1: Write setup.py**

```python
# setup.py
"""py2app build config for macmonitor. Build with:  python setup.py py2app"""
from setuptools import setup

APP = ["macmonitor.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "macmonitor",
        "CFBundleDisplayName": "macmonitor",
        "CFBundleIdentifier": "com.macmonitor",
        "LSUIElement": True,  # agent app: menu bar only, no Dock icon
    },
    "packages": ["rumps", "psutil"],
}

setup(
    app=APP,
    name="macmonitor",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
```

- [ ] **Step 2: Install py2app and build**

Run:
```bash
.venv/bin/pip install py2app
.venv/bin/python setup.py py2app
```
Expected: a `dist/macmonitor.app` is produced (build may print warnings; it should end without an error).

- [ ] **Step 3: Launch the built app**

Run: `open dist/macmonitor.app`
Expected: the menu bar item appears (no Dock icon). Confirm CPU/RAM/link title and dropdown work as in Task 8.

- [ ] **Step 4: Commit**

```bash
git add setup.py
git commit -m "build: add py2app packaging config"
```

---

## Task 10: README and final verification

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

````markdown
# macmonitor

A tiny macOS **menu bar** system monitor. Shows realtime **CPU %**, **RAM used**,
and **network link speed** in the menu bar title; **disk I/O**, **live network
up/down**, an on-demand **fast.com-style speed test**, and an **auto-start**
toggle in the dropdown.

Menu bar title: `CPU 23% · RAM 8.1G · Wi-Fi 1200M`

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python macmonitor.py
```

## Build a .app

```bash
.venv/bin/pip install py2app
.venv/bin/python setup.py py2app
open dist/macmonitor.app
```

Drag `dist/macmonitor.app` into `/Applications` to install.

## Auto-start at login

Use the **开机自启** item in the dropdown to toggle it. It installs/removes a
LaunchAgent at `~/Library/LaunchAgents/com.macmonitor.plist` that opens
`/Applications/macmonitor.app` at login. (Install the app there first for the
toggle to point at the right place.)

## What the numbers mean

- **Link speed** (title) = your Wi-Fi/Ethernet *negotiated* rate, not actual usage.
- **网络 下载/上传** (dropdown) = current real throughput right now.
- **⚡ 立即测速** = actively measures real achievable speed (uses some data; on-demand only).

## Tests

```bash
.venv/bin/python -m pytest -v
```
````

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 3: Final manual smoke test**

Run `.venv/bin/python macmonitor.py`, confirm against the spec's Testing section:
title updates, dropdown rows populate, disk moves on file copy, net moves on
download, speed test returns a result, auto-start toggle creates/removes the plist.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README with run/build/autostart instructions"
```

---

## Self-Review Notes

- **Spec coverage:** CPU/RAM/link-speed title (Task 8), disk I/O + live net up/down (Tasks 4, 8), fast.com speed test (Task 6, 8), auto-start toggle (Tasks 7, 8), py2app (Task 9), README (Task 10), 2s timer + 30s link-speed cache + background speed test (Task 8), error handling for missing counters/link/speed-test (Tasks 4, 5, 6, 8). All spec sections mapped.
- **Unit auto-adaptive K/M** formatting: Task 2. **GB display:** Task 2.
- **Type consistency:** `RateCalc.update(read, write, now)` used identically in Tasks 3 and 8; `run_speed_test()` returns `{ok, down_mbps, up_mbps}` consumed in Task 8; `autostart.enable/disable/is_enabled` defined in Task 7 and called in Task 8.
