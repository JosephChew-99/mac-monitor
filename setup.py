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
        # NOT recover it — only a fresh id does (see Stats issue #3120). This is the
        # 2nd bump (com.macmonitor -> com.josephchew.macmonitor -> here); reinstalling
        # the SAME id many times is what stuck it, so avoid churn. Bump again if stuck.
        "CFBundleIdentifier": "com.josephchew.macmon",
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
