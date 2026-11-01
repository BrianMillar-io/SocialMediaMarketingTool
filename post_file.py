#!/usr/bin/env python3
"""Post a reel you already have (made by Claude or anyone) to @blck.mssv right now.
usage: post_file.py VIDEO.mp4
Uses the caption, hashtags and audio name for this week's Infected Mushroom reel unless
you pass --caption-file FILE.
"""
import csv, datetime, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import poster

CAPTION = """Opening for Infected Mushroom at Music Box. Warmed it up our way.

Full set on Mixcloud: link in bio.

#melodictechno #psytrance #sandiegotechno #musicbox #infectedmushroom"""
AUDIO_NAME = "BLCK.MSSV - Live at Music Box w/ Infected Mushroom"

args = sys.argv[1:]
if not args or not Path(args[0]).expanduser().exists():
    raise SystemExit("Give the path to the video, e.g. post_file.py ~/BLCKMSSV-Poster/reels/BLCKMSSV-reel-infected-mushroom-orbit.mp4")
video = str(Path(args[0]).expanduser())
caption = CAPTION
if "--caption-file" in args:
    caption = Path(args[args.index("--caption-file") + 1]).expanduser().read_text().strip()

settings = poster.load(poster.SETTINGS, None)
token = poster.keychain_get("page_token")
print("Uploading to Instagram. This takes 1-3 minutes, leave this window open...")
for attempt in range(1, 4):
    try:
        media_id, link = poster.ig_publish(video, caption, settings["ig_user_id"], token, AUDIO_NAME)
        break
    except Exception as e:
        print(f"Attempt {attempt} failed: {e}")
        if attempt == 3 or "token" in str(e).lower():
            raise SystemExit("Not posted. Send Claude a screenshot of this window.")
        time.sleep(20)
poster.log(f"Posted {Path(video).name} by hand -> {link}")
with open(poster.LOGS / "posts.csv", "a", newline="") as f:
    csv.writer(f).writerow([datetime.datetime.now().isoformat(timespec="minutes"), "infected-mushroom",
                            1745, "white-stacked-pent.png", link, "manual: orbit reel"])
print("\nPosted: " + link)
