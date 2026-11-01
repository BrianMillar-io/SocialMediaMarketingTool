#!/bin/bash
# BLCK.MSSV Poster installer for macOS.
# Run with:  bash ~/Downloads/BLCKMSSV-Poster/install.sh
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/BLCKMSSV-Poster"
SERVICE="blckmssv-poster"
IG_USER_ID="17841467466490384"
PAGE_ID="2355485891355742"
API="https://graph.facebook.com/v26.0"
PLIST="$HOME/Library/LaunchAgents/com.blckmssv.poster.plist"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }

say "BLCK.MSSV Poster setup"

# 1. Python ----------------------------------------------------------------
if ! python3 -c 'print(1)' >/dev/null 2>&1; then
  say "macOS needs its free developer tools for Python. A window will pop up: click Install, wait, then run this installer again."
  xcode-select --install || true
  exit 0
fi
PY="$(command -v python3)"
"$PY" -c 'import sys; assert sys.version_info >= (3, 9)' || { echo "Python 3.9 or newer is needed."; exit 1; }

# 2. Copy the app into your home folder ----------------------------------------
say "Installing to $APP"
mkdir -p "$APP"
if [ "$SRC" != "$APP" ]; then cp -R "$SRC/poster.py" "$SRC/logos" "$SRC/fonts" "$SRC/install.sh" "$APP/"; fi
mkdir -p "$APP/sets" "$APP/logs" "$APP/reels"

if [ ! -d "$APP/venv" ]; then "$PY" -m venv "$APP/venv"; fi
"$APP/venv/bin/pip" install --quiet --upgrade pip
"$APP/venv/bin/pip" install --quiet numpy pillow requests imageio-ffmpeg
echo "Python packages installed."

# 3. Set recordings ------------------------------------------------------------
# macOS blocks background jobs from reading Desktop/Documents/Downloads, so the
# sets are copied into the app's own folder.
say "Looking for your BLCKMSSV-Content folder"
CONTENT=""
for d in "$HOME/Desktop" "$HOME/Documents" "$HOME/Downloads" "$HOME" "$HOME/Music"; do
  if [ -d "$d/BLCKMSSV-Content" ]; then CONTENT="$d/BLCKMSSV-Content"; break; fi
done
if [ -z "$CONTENT" ]; then
  echo "Couldn't find it. Drag the BLCKMSSV-Content folder into this window, then press Return:"
  read -r CONTENT; CONTENT="${CONTENT%/}"; CONTENT="${CONTENT//\\ / }"; CONTENT="${CONTENT//\'/}"
fi
if [ -d "$CONTENT/sets" ]; then
  cp -n "$CONTENT/sets/"* "$APP/sets/" 2>/dev/null || true
  echo "Copied sets:"; ls -1 "$APP/sets"
else
  echo "No sets folder found there. You can drop recordings into $APP/sets later."
fi

cat > "$APP/settings.json" <<EOF
{"content_dir": "$APP", "ig_user_id": "$IG_USER_ID", "page_id": "$PAGE_ID"}
EOF

# 4. Instagram connection ------------------------------------------------------
if security find-generic-password -s "$SERVICE" -a page_token >/dev/null 2>&1; then
  say "Instagram is already connected. Type R and press Return to reconnect, or just press Return to keep it."
  read -r ANSWER
else
  ANSWER="R"
fi

if [ "$ANSWER" = "R" ] || [ "$ANSWER" = "r" ]; then
  say "Connecting Instagram"
  echo "You need three things from developers.facebook.com. Nothing you paste here is shown on screen or saved in a file."
  echo
  echo "App ID: My Apps > BLCKMSSV Poster > App settings > Basic (the number at the top)."
  read -r -p "Paste App ID and press Return: " APP_ID
  echo
  echo "App secret: same page, click Show next to App secret."
  read -r -s -p "Paste App secret and press Return: " APP_SECRET; echo
  echo
  echo "Access token: Graph API Explorer > Generate Access Token > copy the token."
  read -r -s -p "Paste Access token and press Return: " SHORT_TOKEN; echo

  RESULT=$("$APP/venv/bin/python" - "$APP_ID" "$APP_SECRET" "$SHORT_TOKEN" "$PAGE_ID" "$IG_USER_ID" "$API" <<'PYEOF'
import sys, requests
app_id, secret, short, page_id, ig_id, api = sys.argv[1:7]
r = requests.get(f"{api}/oauth/access_token", params={
    "grant_type": "fb_exchange_token", "client_id": app_id,
    "client_secret": secret, "fb_exchange_token": short}, timeout=30).json()
if "access_token" not in r:
    print("ERROR " + r.get("error", {}).get("message", str(r))); sys.exit()
long_user = r["access_token"]
pages = requests.get(f"{api}/me/accounts", params={
    "fields": "id,name,access_token,instagram_business_account", "access_token": long_user}, timeout=30).json()
page = next((p for p in pages.get("data", []) if p["id"] == page_id), None)
if not page:
    print("ERROR The BLCK.MSSV page wasn't in the token. Generate a new token and pick BLCK.MSSV."); sys.exit()
if page.get("instagram_business_account", {}).get("id") != ig_id:
    print("ERROR @blck.mssv isn't linked to that token."); sys.exit()
check = requests.get(f"{api}/{ig_id}", params={"fields": "username", "access_token": page["access_token"]}, timeout=30).json()
if "username" not in check:
    print("ERROR " + check.get("error", {}).get("message", str(check))); sys.exit()
print("OK " + check["username"] + " " + page["access_token"])
PYEOF
)
  unset APP_SECRET SHORT_TOKEN
  case "$RESULT" in
    OK*)
      USERNAME=$(echo "$RESULT" | cut -d' ' -f2)
      PAGE_TOKEN=$(echo "$RESULT" | cut -d' ' -f3)
      security delete-generic-password -s "$SERVICE" -a page_token >/dev/null 2>&1 || true
      security add-generic-password -s "$SERVICE" -a page_token -w "$PAGE_TOKEN" -U
      unset PAGE_TOKEN RESULT
      echo "Connected to @$USERNAME. The key is stored in your Mac's Keychain and doesn't expire."
      ;;
    *)
      echo "$RESULT"; echo "Nothing was saved. Fix the issue above and run the installer again."; exit 1;;
  esac
fi

# 5. Schedule (laptop's local time) --------------------------------------------
say "Setting the posting schedule: Mon 3pm, Tue 7pm, Wed 6pm, Thu 12pm, Fri 6pm"
mkdir -p "$HOME/Library/LaunchAgents"
slot() { echo "<dict><key>Weekday</key><integer>$1</integer><key>Hour</key><integer>$2</integer><key>Minute</key><integer>0</integer></dict>"; }
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.blckmssv.poster</string>
  <key>ProgramArguments</key><array>
    <string>$APP/venv/bin/python</string><string>$APP/poster.py</string><string>run</string>
  </array>
  <key>StartCalendarInterval</key><array>
    $(slot 1 15) $(slot 2 19) $(slot 3 18) $(slot 4 12) $(slot 5 18)
  </array>
  <key>StandardOutPath</key><string>$APP/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$APP/logs/launchd.log</string>
  <key>WorkingDirectory</key><string>$APP</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# 6. Shortcuts you can double-click --------------------------------------------
cat > "$APP/Preview next reel.command" <<EOF
#!/bin/bash
"$APP/venv/bin/python" "$APP/poster.py" preview
EOF
cat > "$APP/Post now.command" <<EOF
#!/bin/bash
read -r -p "Post the next reel to Instagram right now? Type yes: " A
[ "\$A" = "yes" ] && "$APP/venv/bin/python" "$APP/poster.py" run --force
EOF
cat > "$APP/Status.command" <<EOF
#!/bin/bash
"$APP/venv/bin/python" "$APP/poster.py" status; tail -n 20 "$APP/logs/poster.log" 2>/dev/null
EOF
cat > "$APP/Pause posting.command" <<EOF
#!/bin/bash
launchctl bootout "gui/\$(id -u)" "$PLIST" && echo "Paused. Run install.sh again to resume."
EOF
chmod +x "$APP/"*.command

say "Done."
echo "Your poster lives in: $APP"
echo "New set recordings go in: $APP/sets"
echo
echo "Next: double-click 'Preview next reel' to watch one, then 'Post now' for the test post."
open "$APP"
