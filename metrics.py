"""Pure, testable system-metric helpers for macmonitor. No rumps imports."""

_KB = 1024
_MB = 1024 ** 2
_GB = 1024 ** 3

import re
import subprocess

import psutil

# Prime psutil's cpu_percent so the first real call returns a meaningful value
# (the very first call always returns 0.0 by design).
psutil.cpu_percent(interval=None)


def fmt_rate(bytes_per_sec: float) -> str:
    """Bytes/sec -> compact string. <1 MB/s shows KB ('820K'), else MB ('1.2M')."""
    if bytes_per_sec >= _MB:
        return f"{bytes_per_sec / _MB:.1f}M"
    return f"{int(bytes_per_sec / _KB)}K"


def fmt_gb(num_bytes: float) -> str:
    """Bytes -> GiB with one decimal, no unit suffix (e.g. '8.1')."""
    return f"{num_bytes / _GB:.1f}"


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
