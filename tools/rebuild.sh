#!/bin/bash
# Rebuild macmonitor.app from source and replace the running instance.
#
#   ./tools/rebuild.sh
#
# Also runs automatically after `git pull` via the post-merge hook
# (see tools/install-hooks.sh). Safe to run by hand any time.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="macmonitor.app"
INSTALL_DIR="/Applications"
cd "$REPO_DIR"

echo "==> rebuilding $APP_NAME from $REPO_DIR"

# 1. venv (py2app lives here)
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# 2. clean build
rm -rf build dist
python setup.py py2app >/tmp/macmon_build.log 2>&1 || {
  echo "!! build failed — see /tmp/macmon_build.log"; tail -20 /tmp/macmon_build.log; exit 1; }
echo "==> build ok -> dist/$APP_NAME"

# 3. stop the running instance (ignore if not running)
pkill -f "$INSTALL_DIR/$APP_NAME/Contents/MacOS/macmonitor" 2>/dev/null || true
sleep 1

# 4. swap in the fresh bundle
rm -rf "${INSTALL_DIR:?}/$APP_NAME"
cp -R "dist/$APP_NAME" "$INSTALL_DIR/"

# 5. relaunch (absolute /usr/bin/open — bare `open` is aliased to Sublime here)
/usr/bin/open -a "$INSTALL_DIR/$APP_NAME"
sleep 2

PID="$(pgrep -f "$INSTALL_DIR/$APP_NAME/Contents/MacOS/macmonitor" || true)"
if [ -n "$PID" ]; then
  echo "==> running: pid $PID"
else
  echo "!! app did not come up — check the menu bar / Console"; exit 1
fi
