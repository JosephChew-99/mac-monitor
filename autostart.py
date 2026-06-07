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
