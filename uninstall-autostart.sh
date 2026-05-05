#!/usr/bin/env bash
set -euo pipefail

LABEL="com.yyt.trendradar.stack"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_DST" >/dev/null 2>&1 || true
rm -f "$PLIST_DST"

echo "TrendRadar autostart is removed."
