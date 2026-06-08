"""Pure, testable system-metric helpers for macmonitor. No rumps imports."""

import re
import subprocess
import time
import urllib.request

import psutil

# Prime psutil's cpu_percent so the first real call returns a meaningful value
# (the very first call always returns 0.0 by design).
psutil.cpu_percent(interval=None)

_KB = 1024
_MB = 1024 ** 2
_GB = 1024 ** 3


def fmt_rate(bytes_per_sec: float) -> str:
    """Bytes/sec -> compact string. <1 MB/s shows KB ('820K'), else MB ('1.2M')."""
    if bytes_per_sec >= _MB:
        return f"{bytes_per_sec / _MB:.1f}M"
    return f"{int(bytes_per_sec / _KB)}K"


def fmt_gb(num_bytes: float) -> str:
    """Bytes -> GiB with one decimal, no unit suffix (e.g. '8.1').

    Binary GiB (matches Activity Monitor, which reports memory in GiB).
    """
    return f"{num_bytes / _GB:.1f}"


def fmt_gb_decimal(num_bytes: float) -> str:
    """Bytes -> decimal GB with one decimal, no unit suffix (e.g. '775.7').

    Storage uses decimal GB (1 GB = 1e9 bytes) to match Finder / About This Mac.
    """
    return f"{num_bytes / 1_000_000_000:.1f}"


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
            rate = (
                max(0.0, (read - self._prev_read) / dt),
                max(0.0, (write - self._prev_write) / dt),
            )
        # On a zero/negative interval we keep the previous baseline so the next
        # valid sample still measures from the correct point.
        if self._prev_t is None or now > self._prev_t:
            self._prev_read, self._prev_write, self._prev_t = read, write, now
        return rate


def parse_vm_stat(output: str):
    """Parse `vm_stat` output -> (page_size_bytes, {page-category: count})."""
    psm = re.search(r"page size of (\d+)", output)
    page_size = int(psm.group(1)) if psm else 4096

    def pg(label):
        m = re.search(re.escape(label) + r":\s+(\d+)\.", output)
        return int(m.group(1)) if m else 0

    return page_size, {
        "free": pg("Pages free"),
        "speculative": pg("Pages speculative"),
        "wired": pg("Pages wired down"),
        "purgeable": pg("Pages purgeable"),
        "compressor": pg("Pages occupied by compressor"),
        "file_backed": pg("File-backed pages"),
        "anonymous": pg("Anonymous pages"),
    }


def mem_used_bytes(total_bytes: int, page_size: int, pages: dict) -> int:
    """Activity Monitor's "Memory Used" = Physical − Cached Files − Free.

    The panel relation is `Physical = Used + Cached Files + Free`, so the headline
    number is the physical RAM minus everything macOS can reclaim on demand:
    free pages, speculative (read-ahead) pages, and file-backed cache. Summing
    App + Wired + Compressed instead under-counts by the dirty/mapped pages that
    AM still folds into "Used".
    """
    reclaimable = pages["free"] + pages["speculative"] + pages["file_backed"]
    return max(0, total_bytes - reclaimable * page_size)


def mac_memory() -> dict:
    """RAM usage matching Activity Monitor. Falls back to psutil if vm_stat fails."""
    total = psutil.virtual_memory().total
    try:
        out = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=5
        ).stdout
        page_size, pages = parse_vm_stat(out)
        used = mem_used_bytes(total, page_size, pages)
    except Exception:
        vm = psutil.virtual_memory()
        used = vm.used
    pct = (100.0 * used / total) if total else 0.0
    return {"used": used, "total": total, "pct": pct}


def sample_cpu_ram() -> dict:
    """Snapshot CPU percent (since last call) and Activity-Monitor-style RAM."""
    mem = mac_memory()
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used": mem["used"],
        "ram_total": mem["total"],
        "ram_pct": mem["pct"],
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


def disk_space(path: str = "/") -> dict:
    """Storage capacity for the volume holding `path` (default boot volume).

    Matches Finder / About This Mac by using NSURL's volume keys: the total
    capacity and "available for important usage", which (unlike psutil's free)
    counts purgeable space the OS can reclaim — that's the number Finder shows.
    Used = total - available. Falls back to psutil if the API is unavailable.
    """
    try:
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(path)
        ok_t, total, _ = url.getResourceValue_forKey_error_(
            None, "NSURLVolumeTotalCapacityKey", None
        )
        ok_a, avail, _ = url.getResourceValue_forKey_error_(
            None, "NSURLVolumeAvailableCapacityForImportantUsageKey", None
        )
        if ok_t and ok_a and total and avail is not None:
            total, free = int(total), int(avail)
            used = max(0, total - free)
            pct = (100.0 * used / total) if total else 0.0
            return {"total": total, "used": used, "free": free, "pct": pct}
    except Exception:
        pass

    u = psutil.disk_usage(path)
    used = u.total - u.free
    pct = (100.0 * used / u.total) if u.total else 0.0
    return {"total": u.total, "used": used, "free": u.free, "pct": pct}


def parse_airport_tx_rate(sp_output: str):
    """Extract the link rate (Mbps int) from `system_profiler SPAirPortDataType`.

    macOS 26 (Tahoe) renamed the field 'Tx Rate' -> 'Transmit Rate'; match both.
    """
    m = re.search(r"(?:Transmit Rate|Tx Rate):\s*([0-9]+)", sp_output)
    return int(m.group(1)) if m else None


def read_link_speed():
    """Return a short label like 'Wi-Fi 1152M', or None if unavailable.

    Uses CoreWLAN's transmitRate() — instant and permission-free (no SSID needed).
    `system_profiler SPAirPortDataType` was dropped: on macOS 26 it can take >10s
    (blocking) and renamed the field. Best-effort; never raises.
    """
    try:
        import CoreWLAN

        iface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interface()
        if iface is not None:
            rate = iface.transmitRate()  # Mbps
            if rate and rate > 0:
                return f"Wi-Fi {int(rate)} Mbps"
    except Exception:
        pass
    return None


_DOWN_URL = "https://speed.cloudflare.com/__down?bytes={n}"
_UP_URL = "https://speed.cloudflare.com/__up"
_DOWN_BYTES = 25_000_000
_UP_BYTES = 10_000_000
_SPEED_TIMEOUT = 30
# Cloudflare's speed endpoints return 403 to the default urllib User-Agent,
# so send a browser-like one.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def mbps(num_bytes: float, seconds: float) -> float:
    """Bytes transferred over `seconds` -> megabits per second, 1 decimal."""
    if seconds <= 0:
        return 0.0
    return round((num_bytes * 8) / seconds / 1_000_000, 1)


def _http_download_bytes(nbytes: int, timeout: float):
    """Download nbytes from Cloudflare; return (bytes_read, elapsed_seconds)."""
    req = urllib.request.Request(_DOWN_URL.format(n=nbytes), headers={"User-Agent": _UA})
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
    req = urllib.request.Request(
        _UP_URL, data=payload, method="POST",
        headers={"User-Agent": _UA, "Content-Type": "application/octet-stream"},
    )
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()
    return nbytes, time.monotonic() - start


def run_speed_test() -> dict:
    """Blocking fast.com-style test. Returns dict with ok/down_mbps/up_mbps."""
    try:
        dn_bytes, dn_t = _http_download_bytes(_DOWN_BYTES, _SPEED_TIMEOUT)
        up_bytes, up_t = _http_upload_bytes(_UP_BYTES, _SPEED_TIMEOUT)
        return {
            "ok": True,
            "down_mbps": mbps(dn_bytes, dn_t),
            "up_mbps": mbps(up_bytes, up_t),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
