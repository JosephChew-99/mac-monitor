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
        # The old "com.macmonitor" id got stuck in a bad state (status item created
        # but positioned off-screen / never shown). A fresh id sidesteps that stuck
        # state — see Stats issue #3120. Bump this id again if it ever gets stuck.
        "CFBundleIdentifier": "com.josephchew.macmonitor",
        "LSUIElement": True,  # agent app: menu bar only, no Dock icon
    },
    # CoreWLAN is imported lazily inside metrics.read_link_speed(), so list it
    # explicitly — py2app's static analysis won't otherwise bundle it.
    "packages": ["rumps", "psutil"],
    "includes": ["CoreWLAN"],
}

setup(
    app=APP,
    name="macmonitor",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
