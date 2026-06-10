# setup.py
"""py2app build config for macmonitor. Build with:  python setup.py py2app"""
from setuptools import setup

APP = ["macmonitor.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "macmonitor",
        "CFBundleDisplayName": "macmonitor",
        # NOTE: macOS 26 (Tahoe) keeps per-bundle-ID menu-bar state in ControlCenter.
        # A bundle id can get stuck in a bad state (status item created but parked
        # off-screen / never shown); clearing state / restarting ControlCenter does
        # NOT recover it — only a fresh id does (see Stats issue #3120). History:
        # com.macmonitor -> com.josephchew.macmonitor -> com.josephchew.macmon ->
        # here. Reinstalling the SAME id (even once, after the state is touched) can
        # re-trigger the park, so avoid churn. Bump the trailing token if stuck again.
        "CFBundleIdentifier": "com.josephchew.macmon2",
        "LSUIElement": True,  # agent app: menu bar only, no Dock icon
    },
    # CoreWLAN (read_link_speed) and Foundation (disk_space) are imported lazily,
    # so list them explicitly — py2app's static analysis won't otherwise bundle them.
    "packages": ["rumps", "psutil"],
    "includes": ["CoreWLAN", "Foundation"],
}

setup(
    app=APP,
    name="macmonitor",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
