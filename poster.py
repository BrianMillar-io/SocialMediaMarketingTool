#!/usr/bin/env python3
"""BLCK.MSSV auto-poster.

Picks the next set and drop, renders a black-and-white space reel, writes the
caption and publishes it to Instagram through the official API.

Commands:
  poster.py run         render + post (what the schedule calls)
  poster.py preview     render the next reel only and open it
                        (add --look footage / orbit / warp to try a specific background)
  poster.py status      show what has been posted and what is next
Add --dry-run to `run` to do everything except the Instagram upload,
or --force to post right now outside the schedule (used for the test post).
"""
import csv, json, math, os, random, subprocess, sys, time, datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HOME = Path(__file__).resolve().parent
SETTINGS = HOME / "settings.json"
STATE = HOME / "state.json"
LOGS = HOME / "logs"
OUT = HOME / "reels"
KEYCHAIN_SERVICE = "blckmssv-poster"
API_VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{API_VERSION}"

HASHTAGS = "#melodictechno #indiedance #progressivehouse #sandiegotechno #djset"
TAGS = {
    "infected-mushroom": "#melodictechno #psytrance #sandiegotechno #musicbox #infectedmushroom",
    "oakenfold": "#melodichouse #progressivetrance #sandiegotechno #musicbox #pauloakenfold",
    "alpha": "#indiedance #melodictechno #progressivehouse #nudisco #sandiegotechno",
    "beta": "#techhouse #nudisco #basshouse #melodichouse #sandiegotechno",
}
PROFILE_MIXCLOUD = "https://www.mixcloud.com/BLCKMSSV/"

SETS = {
    "infected-mushroom": {
        "match": ["infected", "mushroom"],
        "title": ("LIVE @ MUSIC BOX", "W/ INFECTED MUSHROOM"),
        "keyword": "MUSHROOM",
        "mixcloud": "https://www.mixcloud.com/BLCKMSSV/blckmssv-live-music-box-with-infected-mushroom/",
        "logo": "white-stacked-pent.png",  # always the pentagram
        "stories": [
            "Opening for Infected Mushroom at Music Box. Warmed it up our way.",
            "Music Box, San Diego. The moment the room locked in.",
            "From our set before Infected Mushroom took over.",
            "This one hit different on the Music Box system.",
            "Psy edges, melodic heart. Live at Music Box.",
        ],
    },
    "oakenfold": {
        "match": ["oaken"],
        "title": ("LIVE @ MUSIC BOX", "W/ PAUL OAKENFOLD"),
        "keyword": "OAKENFOLD",
        "mixcloud": "https://www.mixcloud.com/BLCKMSSV/blckmssv-live-music-box-presents-paul-oakenfold/",
        "logo": None,
        "stories": [
            "Before Oakenfold took over, we had the floor.",
            "Music Box presents Paul Oakenfold. Our warm-up, start to finish.",
            "Peak time at Music Box, San Diego.",
            "The build before the legend.",
        ],
    },
    "beta": {
        "match": ["beta"],
        "title": ("BETA", "FULL MIX ON MIXCLOUD"),
        "keyword": "BETA",
        "mixcloud": "https://www.mixcloud.com/BLCKMSSV/blckmssv-beta/",
        "logo": "white-stacked-disco.png",
        "stories": [
            "BETA. Two hours of funk-driven house at 128.",
            "From BETA: indie tech, nu-disco and bass house in one ride.",
            "The groove section of BETA.",
            "New studio mix. Built for the afterparty.",
            "BETA is up. This is the part you replay.",
        ],
    },
    "alpha": {
        "match": ["alpha"],
        "title": ("ALPHA", "FULL MIX ON MIXCLOUD"),
        "keyword": "ALPHA",
        "mixcloud": "https://www.mixcloud.com/BLCKMSSV/blckmssv-alpha/",
        "logo": None,
        "stories": [
            "From ALPHA. Ninety minutes of where BLCK.MSSV started.",
            "The blend everyone asks about.",
            "For the 2 am crowd.",
            "Indie dance, melodic techno, no brakes.",
            "Patience track. Worth the wait.",
        ],
    },
}

W, H, FPS, CLIP = 1080, 1920, 30, 24.0


# ---------------------------------------------------------------- helpers
def log(msg):
    LOGS.mkdir(exist_ok=True)
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    with open(LOGS / "poster.log", "a") as f:
        f.write(line + "\n")


def notify(msg):
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "BLCK.MSSV Poster"'],
                       capture_output=True)


def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save(path, data):
    path.write_text(json.dumps(data, indent=2))


def keychain_get(account):
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"No {account} in Keychain. Run install.sh again.")
    return r.stdout.strip()


def ffmpeg_bin():
    for p in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        if Path(p, "ffmpeg").exists():
            return str(Path(p, "ffmpeg"))
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG = ffmpeg_bin()
SLOTS = {0: (15, 0), 1: (19, 0), 2: (18, 0), 3: (12, 0), 4: (18, 0)}  # Mon-Fri, laptop's local time


def in_slot(now=None, grace_hours=2):
    """True if now is within grace_hours after today's posting time (catches runs delayed by sleep)."""
    now = now or datetime.datetime.now()
    slot = SLOTS.get(now.weekday())
    if not slot:
        return False
    t = now.replace(hour=slot[0], minute=slot[1], second=0, microsecond=0)
    return t <= now <= t + datetime.timedelta(hours=grace_hours)


# ---------------------------------------------------------------- sets & drops
def find_sets(content_dir):
    sets = {}
    folder = Path(content_dir) / "sets"
    for f in sorted(folder.iterdir()) if folder.exists() else []:
        if f.suffix.lower() not in (".mp3", ".wav", ".m4a", ".aiff", ".aif", ".flac"):
            continue
        name = f.stem.lower()
        key = next((k for k, v in SETS.items() if any(m in name for m in v["match"])), None)
        if key is None:
            key = f.stem
        sets[key] = f
    return sets


def set_meta(key, path):
    if key in SETS:
        return SETS[key]
    nice = path.stem.replace("_", " ").replace("-", " ").upper()
    return {"title": ("BLCK.MSSV", nice), "keyword": "SET", "mixcloud": PROFILE_MIXCLOUD, "logo": None,
            "stories": ["New from BLCK.MSSV.", "Straight from the decks."]}


def find_drops(path, n=12):
    """Seconds where the music jumps from quieter to loud: the drops."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", "2000", "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    secs = len(x) // 2000
    rms = np.sqrt((x[: secs * 2000].reshape(secs, 2000) ** 2).mean(1)) + 1e-6
    db = 20 * np.log10(rms)
    cands = []
    for t in range(120, secs - 120):
        cands.append((db[t:t + 16].mean() - db[t - 8:t].mean(), t))
    cands.sort(reverse=True)
    picked = []
    for score, t in cands:
        if all(abs(t - p) > 60 for p in picked):
            picked.append(t)
        if len(picked) == n:
            break
    return picked


# ---------------------------------------------------------------- choosing
def choose(state, sets):
    last = state.get("last_set")
    keys = list(sets)
    if not keys:
        raise SystemExit("No set recordings found in the sets folder.")
    pool = [k for k in keys if k != last] or keys
    if "oakenfold" in pool and random.random() < 0.5:
        key = "oakenfold"
    else:
        used_at = state.get("set_last_used", {})
        key = min(pool, key=lambda k: used_at.get(k, 0))
    path = sets[key]
    cache = state.setdefault("drops", {})
    sig = f"{path.name}:{path.stat().st_size}"
    if cache.get(key, {}).get("sig") != sig:
        log(f"Analyzing {path.name} for drops...")
        cache[key] = {"sig": sig, "drops": find_drops(path), "used": []}
    entry = cache[key]
    unused = [d for d in entry["drops"] if d not in entry["used"]]
    if not unused:
        entry["used"] = []
        unused = entry["drops"]
    return key, path, unused[0]


# ---------------------------------------------------------------- render
def audio_features(audio, start, dur):
    sr = 22050
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(audio),
                          "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    n, hop = int(dur * FPS), sr // FPS
    win = np.hanning(2048)
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    bass, loud, cent = [], [], []
    for i in range(n):
        seg = x[i * hop: i * hop + 2048]
        if len(seg) < 2048:
            seg = np.pad(seg, (0, 2048 - len(seg)))
        spec = np.abs(np.fft.rfft(seg * win))
        bass.append(spec[(freqs > 35) & (freqs < 120)].mean())
        loud.append(np.sqrt((seg ** 2).mean()))
        cent.append((spec * freqs).sum() / (spec.sum() + 1e-9))

    def norm(a):
        a = np.array(a); lo, hi = np.percentile(a, 5), np.percentile(a, 98)
        return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)
    return norm(bass), norm(loud), float(np.median(cent))


def pick_logo(meta, centroid):
    if meta.get("logo"):
        return meta["logo"]
    # darker / melodic clips get the spiral, brighter / disco-leaning clips the disco ball
    return "white-stacked-spiral.png" if centroid < 1800 else "white-stacked-disco.png"


def render(audio, start, out, line1, line2, cta, logo_name, bass, loud, seed):
    rng = np.random.default_rng(seed)
    N = len(bass)
    kick = np.zeros(N); k = 0
    for i in range(N):
        k = max(bass[i], k * 0.80); kick[i] = k
    speed = np.convolve(loud, np.ones(12) / 12, mode="same")

    logo = Image.open(HOME / "logos" / logo_name).convert("RGBA")
    LW = 640
    logo = logo.resize((LW, int(logo.height * LW / logo.width)), Image.LANCZOS)
    glow = Image.new("RGBA", (logo.width + 200, logo.height + 200), (0, 0, 0, 0))
    glow.paste(logo, (100, 100), logo)
    glow = glow.filter(ImageFilter.GaussianBlur(28))

    neb = rng.random((24, 14))
    neb = Image.fromarray((neb * 255).astype(np.uint8)).resize((W + 400, H + 400), Image.BICUBIC)
    neb = neb.filter(ImageFilter.GaussianBlur(60))
    neb = Image.eval(neb, lambda v: max(0, v - 110) * 0.55)

    S = 900
    sx = rng.uniform(-1, 1, S); sy = rng.uniform(-1, 1, S); sz = rng.uniform(0.05, 1, S)
    cx, cy = W / 2, H * 0.42
    fbold = ImageFont.truetype(str(HOME / "fonts" / "Inter-SemiBold.otf"), 52)
    fmed = ImageFont.truetype(str(HOME / "fonts" / "Inter-Medium.otf"), 42)
    fsm = ImageFont.truetype(str(HOME / "fonts" / "Inter-Medium.otf"), 34)
    dur = N / FPS

    ff = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-ss", str(start), "-t", str(dur), "-i", str(audio),
                           "-af", f"afade=t=in:d=0.5,afade=t=out:st={dur - 1.5}:d=1.5",
                           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19",
                           "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest",
                           "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    for f in range(N):
        t = f / FPS
        v = 0.004 + 0.035 * speed[f] ** 2
        ox = int(200 + 120 * math.sin(t * 0.15)); oy = int(200 + 150 * math.cos(t * 0.11))
        frame = neb.crop((ox, oy, ox + W, oy + H)).convert("RGB")
        d = ImageDraw.Draw(frame)
        z0 = sz.copy()
        sz -= v
        dead = sz <= 0.03
        sz[dead] = 1.0; sx[dead] = rng.uniform(-1, 1, dead.sum()); sy[dead] = rng.uniform(-1, 1, dead.sum())
        z0[dead] = 1.0
        px = cx + sx / sz * 420; py = cy + sy / sz * 420
        qx = cx + sx / z0 * 420; qy = cy + sy / z0 * 420
        b = np.clip((1 - sz) * 1.3, 0, 1)
        for i in range(S):
            if -50 < px[i] < W + 50 and -50 < py[i] < H + 50:
                c = int(255 * b[i]); w = 1 if sz[i] > 0.4 else 2 if sz[i] > 0.15 else 3
                d.line((qx[i], qy[i], px[i], py[i]), fill=(c, c, c), width=w)
        s = 1.0 + 0.10 * kick[f]
        L = logo.resize((int(logo.width * s), int(logo.height * s)), Image.BILINEAR)
        G = glow.resize((int(glow.width * s), int(glow.height * s)), Image.BILINEAR)
        G.putalpha(G.split()[3].point(lambda a: int(a * (0.35 + 0.65 * kick[f]))))
        frame.paste(G, (int(cx - G.width / 2), int(cy - G.height / 2)), G)
        frame.paste(L, (int(cx - L.width / 2), int(cy - L.height / 2)), L)
        for txt, font, y, a in ((line1, fbold, 1500, 255), (line2, fmed, 1570, 200), (cta, fsm, 1740, 150)):
            tw = d.textlength(txt, font=font)
            d.text(((W - tw) / 2, y), txt, font=font, fill=(a, a, a))
        d.line((W / 2 - 90, 1660, W / 2 + 90, 1660), fill=(120, 120, 120), width=3)
        ff.stdin.write(frame.tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed while rendering")


LOOKS = ["warp", "orbit", "footage"]


def pick_look(state, has_footage):
    """Rotate looks so two posts in a row never share a background. Footage, when there is
    some, gets every other post."""
    last = state.get("last_look")
    options = [l for l in LOOKS if l != last and (l != "footage" or has_footage)]
    if has_footage and "footage" in options and last != "footage":
        return "footage"
    used = state.get("look_last_used", {})
    return min(options, key=lambda l: used.get(l, 0))


def make_next(settings, state, force_look=None):
    sets = find_sets(settings["content_dir"])
    key, path, drop = choose(state, sets)
    meta = set_meta(key, path)
    start = max(0, drop - 6)
    bass, loud, centroid = audio_features(path, start, CLIP)
    logo = pick_logo(meta, centroid)
    OUT.mkdir(exist_ok=True)
    stamp = f"{datetime.datetime.now():%Y%m%d-%H%M}"
    cta = "FULL SET: LINK IN BIO"
    import footage
    has_footage = bool(footage.find_footage(settings["content_dir"]))
    look = force_look or pick_look(state, has_footage)
    out = OUT / f"{stamp}-{key}-{drop}-{look}.mp4"
    log(f"Rendering {key} @ {drop // 60}:{drop % 60:02d} with {logo}, look: {look}")
    if look == "footage":
        desc = footage.make_footage_reel(FFMPEG, settings["content_dir"], state, path, start, CLIP, out,
                                         HOME / "logos" / logo, HOME / "fonts",
                                         meta["title"][0], meta["title"][1], cta, seed=drop + int(time.time()) % 1000)
        if desc:
            log(f"Footage: {desc}")
        else:
            log("No usable footage (clips must be longer than 28 seconds); using orbit instead.")
            look = "orbit"
    if look == "orbit":
        import orbit
        orbit.render_orbit(FFMPEG, path, start, CLIP, HOME / "logos" / logo, HOME / "fonts", out,
                           meta["title"][0], meta["title"][1], cta, seed=drop)
    elif look == "warp":
        render(path, start, out, meta["title"][0], meta["title"][1], cta, logo, bass, loud, seed=drop)
    last_story = state.get("last_story", {}).get(key)
    stories = [s for s in meta["stories"] if s != last_story] or meta["stories"]
    story = random.choice(stories)
    caption = (f"{story}\n\nFull set on Mixcloud: link in bio.\n"
               f"\n{TAGS.get(key, HASHTAGS)}")
    return {"key": key, "drop": drop, "file": str(out), "caption": caption, "logo": logo, "story": story,
            "look": look}


# ---------------------------------------------------------------- Instagram
def ig_publish(video, caption, ig_id, token, audio_name="BLCK.MSSV"):
    import requests

    def check(r):
        j = r.json()
        if "error" in j:
            e = j["error"]
            if e.get("code") == 190:
                raise RuntimeError("Instagram token expired or revoked. Run install.sh again to reconnect.")
            raise RuntimeError(f"Instagram error {e.get('code')}: {e.get('message')}")
        return j

    j = check(requests.post(f"{GRAPH}/{ig_id}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "audio_name": audio_name, "access_token": token}, timeout=60))
    cid = j["id"]
    uri = j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{API_VERSION}/{cid}"
    data = Path(video).read_bytes()
    up = requests.post(uri, headers={"Authorization": f"OAuth {token}", "offset": "0",
                                     "file_size": str(len(data))}, data=data, timeout=600)
    if up.status_code >= 300:
        raise RuntimeError(f"Upload failed: {up.status_code} {up.text[:200]}")
    for _ in range(90):  # up to 15 minutes of processing
        st = check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status",
                                                          "access_token": token}, timeout=30))
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {st.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram took too long to process the video.")
    pub = check(requests.post(f"{GRAPH}/{ig_id}/media_publish",
                              data={"creation_id": cid, "access_token": token}, timeout=60))
    link = check(requests.get(f"{GRAPH}/{pub['id']}", params={"fields": "permalink",
                                                              "access_token": token}, timeout=30))
    return pub["id"], link.get("permalink", "")


# ---------------------------------------------------------------- commands
def cmd_run(dry_run=False):
    settings = load(SETTINGS, None)
    if not settings:
        raise SystemExit("settings.json missing. Run install.sh first.")
    state = load(STATE, {})
    lock = HOME / ".running"
    if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
        log("Another run is in progress; skipping."); return
    last = state.get("last_post_time", 0)
    if not dry_run and "--force" not in sys.argv and time.time() - last < 3 * 3600:
        log("Posted less than 3 hours ago (probably a missed run after sleep); skipping."); return
    if not dry_run and "--force" not in sys.argv and not in_slot():
        log("Outside a posting window (laptop was probably asleep at post time); skipping."); return
    lock.touch()
    try:
        item = make_next(settings, state)
        if dry_run:
            log(f"DRY RUN, not posted: {item['file']}\n{item['caption']}")
        else:
            token = keychain_get("page_token")
            media_id, link = ig_publish(item["file"], item["caption"], settings["ig_user_id"], token, {"infected-mushroom": "BLCK.MSSV - Live at Music Box w/ Infected Mushroom", "oakenfold": "BLCK.MSSV - Live at Music Box w/ Paul Oakenfold", "alpha": "BLCK.MSSV - ALPHA", "beta": "BLCK.MSSV - BETA"}.get(item["key"], "BLCK.MSSV"))
            log(f"Posted {item['key']} -> {link}")
            notify(f"Posted a reel from {item['key']}")
            with open(LOGS / "posts.csv", "a", newline="") as f:
                csv.writer(f).writerow([datetime.datetime.now().isoformat(timespec="minutes"), item["key"],
                                        item["drop"], item["logo"], link, item["story"]])
            state["last_post_time"] = time.time()
        # record rotation either way so previews and dry runs advance like real runs
        state["last_set"] = item["key"]
        state.setdefault("set_last_used", {})[item["key"]] = time.time()
        state["drops"][item["key"]]["used"].append(item["drop"])
        state.setdefault("last_story", {})[item["key"]] = item["story"]
        state["last_look"] = item["look"]
        state.setdefault("look_last_used", {})[item["look"]] = time.time()
        save(STATE, state)
        # keep the reels folder small: delete renders older than 14 days
        for f in OUT.glob("*.mp4"):
            if time.time() - f.stat().st_mtime > 14 * 86400:
                f.unlink()
    except Exception as e:
        log(f"FAILED: {e}")
        notify(f"Post failed: {e}"[:200])
        raise
    finally:
        lock.unlink(missing_ok=True)


def cmd_preview():
    settings = load(SETTINGS, None)
    state = load(STATE, {})
    look = sys.argv[sys.argv.index("--look") + 1] if "--look" in sys.argv else None
    item = make_next(settings, state, force_look=look)
    print(f"\nPreview ({item['look']}): {item['file']}\n\nCaption:\n{item['caption']}")
    if sys.platform == "darwin":
        subprocess.run(["open", item["file"]])


def cmd_status():
    state = load(STATE, {})
    print("Last set posted:", state.get("last_set", "none yet"))
    p = LOGS / "posts.csv"
    if p.exists():
        rows = list(csv.reader(open(p)))[-10:]
        print("\nRecent posts:")
        for r in rows:
            print("  ", r[0], r[1], r[4])
    for key, d in state.get("drops", {}).items():
        print(f"{key}: {len(d['drops']) - len(d['used'])} unused drops left")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "run":
        cmd_run(dry_run="--dry-run" in args)
    elif cmd == "preview":
        cmd_preview()
    else:
        cmd_status()
