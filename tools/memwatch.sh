#!/bin/bash
# Samples the running macmonitor's RSS for the 1-day leak observation.
# Logs: ISO8601<TAB>pid<TAB>rss_mb<TAB>etime<TAB>bundle_id   (or "not-running")
LOG="$HOME/Library/Logs/macmonitor_memwatch.log"
ts=$(date "+%Y-%m-%dT%H:%M:%S")
pid=$(pgrep -f "MacOS/macmonitor" | head -1)
if [ -z "$pid" ]; then
  printf '%s\tnot-running\n' "$ts" >> "$LOG"
  exit 0
fi
rss_kb=$(ps -o rss= -p "$pid" | tr -d ' ')
etime=$(ps -o etime= -p "$pid" | tr -d ' ')
bid=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' /Applications/macmonitor.app/Contents/Info.plist 2>/dev/null)
printf '%s\t%s\t%s\t%s\t%s\n' "$ts" "$pid" "$((rss_kb/1024))" "$etime" "$bid" >> "$LOG"
