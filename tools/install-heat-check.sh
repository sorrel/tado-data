#!/usr/bin/env bash
# Install (or reinstall) the daily heat check as a launchd agent.
#
#   tools/install-heat-check.sh
#
# Fills in tools/heat-check.plist.template with this Mac's paths, writes it to
# ~/Library/LaunchAgents and loads it. Safe to run again after moving the repo.
set -euo pipefail

LABEL="uk.local.tado-data.heat-check"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV="$(command -v uv || true)"
LOG="$HOME/Library/Logs/tado-heat-check.log"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ -z "$UV" ]]; then
    echo "uv isn't on your PATH, so the heat check can't be scheduled." >&2
    exit 1
fi

for value in "$UV" "$REPO" "$LOG"; do
    if [[ "$value" == *[\&\<\>\|]* ]]; then
        echo "A path contains a character the plist can't take: $value" >&2
        exit 1
    fi
done

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__UV__|$UV|g" -e "s|__REPO__|$REPO|g" -e "s|__LOG__|$LOG|g" \
    "$REPO/tools/heat-check.plist.template" > "$PLIST"
plutil -lint "$PLIST" > /dev/null

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# macOS can hold back notifications from osascript until they're allowed
# (under Script Editor in System Settings → Notifications). Send one now, so
# a missing permission shows up today rather than at the first fault.
osascript -e 'display notification "Installed. You will only hear from it when something is wrong." with title "Tado heat check"'

echo "Installed: the heat check will run at 07:00 each day, with later runs"
echo "catching up if the Mac was off. Later runs make no Tado requests once"
echo "the day is checked."
echo
echo "A test notification has just been sent. If you didn't see it, allow"
echo "notifications for Script Editor in System Settings → Notifications."
echo "Log: $LOG"
echo
echo "To run it now (this makes real Tado requests, about 19 a day checked):"
echo "  launchctl kickstart gui/$(id -u)/$LABEL"
echo
echo "To remove it:"
echo "  launchctl bootout gui/$(id -u)/$LABEL && rm \"$PLIST\""
