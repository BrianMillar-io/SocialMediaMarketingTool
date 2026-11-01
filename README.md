# SocialMediaMarketingTool

BLCK.MSSV Poster: turns DJ mix recordings into short vertical reels and posts them to Instagram on a schedule, from a Mac.

## What it does

- Scans each mix for its biggest drops and cuts a 24-second clip around one.
- Renders a 1080x1920 reel in one of three looks, rotating so two posts in a row never match:
  - **warp**: black-and-white starfield that speeds up with the music, logo pulsing on the kick
  - **orbit**: circular spectrum around the logo, rings rippling out on every kick
  - **footage**: real gig video (360 or flat) reframed to vertical, with the mix audio laid over it
- Writes the caption and set-specific hashtags (5 max), names the reel's audio after the set.
- Publishes through the official Instagram Graph API (resumable upload, no hosting needed).
- Rotates mixes so the same set never posts twice in a row and each set's drops are used before repeating.

## Files

| File | Purpose |
| --- | --- |
| `poster.py` | Main program: picks the set, drop and look, renders, captions, posts |
| `footage.py` | 360 reframing (ffmpeg `v360`) and flat-video handling for footage reels |
| `orbit.py` | Orbit look renderer |
| `post_file.py` | Post an existing video right now with a fixed caption |
| `install.sh` | macOS installer: Python env, Instagram connection (token kept in Keychain), launchd schedule |
| `logos/`, `fonts/` | BLCK.MSSV logos and Inter fonts used on the reels |

## Install (macOS)

```
bash install.sh
```

The installer asks for the Meta App ID, App secret and a short-lived access token, exchanges them for a non-expiring Page token, and stores it only in the macOS Keychain. Nothing secret is written to disk or committed.

## Use

```
~/BLCKMSSV-Poster/venv/bin/python ~/BLCKMSSV-Poster/poster.py preview              # make the next reel and play it, no posting
~/BLCKMSSV-Poster/venv/bin/python ~/BLCKMSSV-Poster/poster.py preview --look footage
~/BLCKMSSV-Poster/venv/bin/python ~/BLCKMSSV-Poster/poster.py run --force          # post the next reel now
~/BLCKMSSV-Poster/venv/bin/python ~/BLCKMSSV-Poster/poster.py status
```

Scheduled posts run Mon 3 pm, Tue 7 pm, Wed 6 pm, Thu 12 pm, Fri 6 pm (laptop local time). The laptop must be awake; a missed slot is skipped rather than posted late.

## Content folders (not in the repo)

- `sets/`: mix recordings (MP3/WAV/AIFF). Put the set name in the file name (for example `BLCKMSSV-BETA.mp3`).
- `footage/`: gig video. For Insta360, export as a 360 MP4 (equirectangular), a few minutes per file.

Mixes, videos, settings, logs and posting history are git-ignored.
