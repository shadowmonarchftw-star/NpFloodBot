#!/bin/bash
# Stop and remove macOS LaunchAgent
PLIST_FILE="$HOME/Library/LaunchAgents/com.nepalflood.bot.plist"
launchctl unload "$PLIST_FILE" 2>/dev/null || true
rm -f "$PLIST_FILE"
echo "🛑 Background service stopped and removed."
