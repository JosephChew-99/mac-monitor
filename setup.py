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
