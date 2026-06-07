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
