#!/bin/bash
# Install macOS LaunchAgent to run Nepal Flood Early Warning Bot every 15 minutes

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.nepalflood.bot.plist"
WORKSPACE="/Users/success/googleweatherbot"
PYTHON_BIN="$WORKSPACE/.venv/bin/python"

mkdir -p "$PLIST_DIR"
mkdir -p "$WORKSPACE/logs"

cat << EOF > "$PLIST_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nepalflood.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$WORKSPACE/main.py</string>
        <string>--once</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$WORKSPACE</string>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$WORKSPACE/logs/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$WORKSPACE/logs/bot_error.log</string>
</dict>
</plist>
EOF

# Unload previous instance if present, then load
launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"

echo "✅ Automatic 15-minute background service installed successfully!"
echo "Status: Running via macOS launchd ($PLIST_FILE)"
echo "Logs: $WORKSPACE/logs/bot.log"
