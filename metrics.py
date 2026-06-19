"""Pure, testable system-metric helpers for macmonitor. No rumps imports."""

import json
import os
import re
import subprocess
import threading
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

    Uses the `statvfs(2)` syscall — total = blocks * frag size, free =
    blocks-available-to-non-root, used = total - free.

    MEMORY: deliberately NOT NSURL. The Finder-style number
    (`NSURLVolumeAvailableCapacityForImportantUsageKey`, which folds in purgeable
    space) is more accurate but its resource-value query leaks native Foundation
    memory on every call — ~0.2-1 KB each, unbounded, which a 2 s refresh turns
    into a steady RSS creep that neither gc nor an autorelease pool can reclaim.
    `statvfs` holds nothing in-process: measured RSS is dead flat across tens of
    thousands of calls. The trade-off is that we don't count purgeable space, so
    "used" reads a little higher than Finder (~12 GB on a typical APFS volume).
    """
    try:
        s = os.statvfs(path)
        total = s.f_blocks * s.f_frsize
        free = s.f_bavail * s.f_frsize  # available to non-root
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
        import objc
        import CoreWLAN

        # autorelease_pool: CoreWLAN's interface()/transmitRate() autorelease a few
        # objects per call; without an explicit pool on this (timer) thread they
        # accrete. Halves the per-call growth; combined with the 30 s throttle in
        # the caller the residual is negligible.
        with objc.autorelease_pool():
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
# A zero-byte download is the cheapest round trip Cloudflare offers; we use it
# to time latency (request out -> response back) the same way speed.cloudflare.com does.
_LATENCY_URL = "https://speed.cloudflare.com/__down?bytes=0"
# /meta returns JSON describing the edge you hit and how Cloudflare sees you
# (colo, city, your public IP, ISP/ASN).
_META_URL = "https://speed.cloudflare.com/meta"
_DOWN_BYTES = 25_000_000
_UP_BYTES = 10_000_000
_SPEED_TIMEOUT = 30
_LATENCY_SAMPLES = 20
_LATENCY_TIMEOUT = 5
_META_TIMEOUT = 5
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


def _round1(v):
    """Round to 1 decimal, passing None through unchanged."""
    return None if v is None else round(v, 1)


def _median(values):
    """Median of a list; None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _jitter(values):
    """Mean of absolute differences between consecutive samples.

    This is the same definition Cloudflare's speed test uses for jitter:
    the average packet-to-packet variation in latency. Needs >=2 samples.
    """
    if len(values) < 2:
        return None
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return sum(diffs) / len(diffs)


def _probe_latency_once(timeout):
    """One round trip to the zero-byte endpoint; returns milliseconds."""
    req = urllib.request.Request(_LATENCY_URL, headers={"User-Agent": _UA})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()
    return (time.monotonic() - start) * 1000.0


def _measure_latency(count, timeout):
    """Probe latency `count` times; returns a list of millisecond samples.

    Individual failed probes are skipped rather than aborting the whole run.
    """
    samples = []
    for _ in range(count):
        try:
            samples.append(_probe_latency_once(timeout))
        except Exception:
            pass
    return samples


def _run_transfer_with_probes(transfer_fn, timeout):
    """Run transfer_fn() in a thread while probing latency in parallel.

    Returns (transfer_result, latency_samples). The probes taken while the
    link is saturated are the "loaded latency" (a.k.a. latency under load).
    Re-raises any exception from transfer_fn so the caller can mark the run failed.
    """
    box = {}

    def runner():
        try:
            box["value"] = transfer_fn()
        except Exception as e:  # noqa: BLE001 - surfaced to caller below
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    probes = []
    t.start()
    while t.is_alive():
        try:
            probes.append(_probe_latency_once(timeout))
        except Exception:
            pass
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"], probes


def _fetch_meta(timeout):
    """Fetch /meta JSON (edge colo, city, your IP, ISP/ASN)."""
    req = urllib.request.Request(_META_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rate(value, thresholds):
    """Map a latency-like value to a 4-level rating using ascending cutoffs.

    thresholds = (great, good, average); anything worse than `average` is bad.
    Lower is better. Returns one of 很好/好/中/差 (great/good/average/bad).
    """
    labels = ["很好", "好", "中", "差"]
    if value is None:
        return "—"
    for i, cutoff in enumerate(thresholds):
        if value <= cutoff:
            return labels[i]
    return labels[3]


def network_quality_score(latency_ms, jitter_ms, loaded_ms):
    """Heuristic video/gaming/chat ratings, mirroring Cloudflare's AIM idea.

    Cloudflare derives these from latency, jitter and loaded latency rather
    than measuring each use case directly; we do the same with a simple
    responsiveness proxy = loaded latency (falling back to idle latency) plus
    jitter. Cutoffs are tuned per use case: gaming is the strictest, streaming
    the most tolerant. Returns a dict of streaming/gaming/chatting -> rating.
    """
    base = loaded_ms if loaded_ms is not None else latency_ms
    if base is None:
        responsiveness = None
    else:
        responsiveness = base + (jitter_ms or 0.0)
    return {
        "streaming": _rate(responsiveness, (150, 400, 800)),
        "gaming": _rate(responsiveness, (75, 150, 300)),
        "chatting": _rate(responsiveness, (100, 250, 500)),
    }


def run_speed_test() -> dict:
    """Blocking Cloudflare speed test.

    Returns a dict with ok plus, on success: down_mbps, up_mbps, latency_ms,
    jitter_ms, loaded_down_ms, loaded_up_ms, scores, and (best effort) server,
    colo, ip, isp. Latency/jitter and the /meta lookup are best-effort: if they
    fail the throughput numbers are still returned.
    """
    try:
        # Best-effort edge/ISP info; never let it sink the run.
        try:
            meta = _fetch_meta(_META_TIMEOUT)
        except Exception:
            meta = None

        # Idle latency + jitter, taken before we saturate the link.
        idle = _measure_latency(_LATENCY_SAMPLES, _LATENCY_TIMEOUT)
        latency_ms = _median(idle)
        jitter_ms = _jitter(idle)

        # Throughput, with latency probed concurrently to get loaded latency.
        (dn_bytes, dn_t), down_probes = _run_transfer_with_probes(
            lambda: _http_download_bytes(_DOWN_BYTES, _SPEED_TIMEOUT), _LATENCY_TIMEOUT
        )
        (up_bytes, up_t), up_probes = _run_transfer_with_probes(
            lambda: _http_upload_bytes(_UP_BYTES, _SPEED_TIMEOUT), _LATENCY_TIMEOUT
        )
        loaded_down_ms = _median(down_probes)
        loaded_up_ms = _median(up_probes)

        result = {
            "ok": True,
            "down_mbps": mbps(dn_bytes, dn_t),
            "up_mbps": mbps(up_bytes, up_t),
            "latency_ms": _round1(latency_ms),
            "jitter_ms": _round1(jitter_ms),
            "loaded_down_ms": _round1(loaded_down_ms),
            "loaded_up_ms": _round1(loaded_up_ms),
            "scores": network_quality_score(
                latency_ms, jitter_ms, loaded_down_ms or loaded_up_ms
            ),
        }
        if meta:
            result["colo"] = meta.get("colo")
            result["server"] = meta.get("city") or meta.get("colo")
            result["ip"] = meta.get("clientIp")
            org = meta.get("asOrganization")
            asn = meta.get("asn")
            if org and asn:
                result["isp"] = f"{org} (AS{asn})"
            elif org:
                result["isp"] = org
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}
