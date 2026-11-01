"""Turn gig footage into a BLCK.MSSV reel.

Drop clips in BLCKMSSV-Poster/footage. Works with:
  - 360 video exported from the Insta360 app/Studio as a normal 360 MP4 (2:1, equirectangular).
    A random part of the scene is reframed into a flat vertical shot, aimed where the most is
    happening (lights, crowd movement), with a slow drift so it doesn't look static.
  - Regular flat video (phone clips, already-reframed exports): center-cropped to vertical.
The camera's own sound is dropped and a clip from the chosen mix plays over it instead.
"""
import math, random, re, subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
VIDEO_EXT = (".mp4", ".mov", ".m4v")
V_FOV = 100.0                                                   # vertical field of view, degrees
H_FOV = math.degrees(2 * math.atan(math.tan(math.radians(V_FOV / 2)) * W / H))  # ~68 for 9:16


def find_footage(content_dir):
    folder = Path(content_dir) / "footage"
    if not folder.exists():
        return []
    return sorted(f for f in folder.iterdir() if f.suffix.lower() in VIDEO_EXT and not f.name.startswith("."))


def probe(ffmpeg, path):
    """Duration (s), width, height from ffmpeg's header output (no ffprobe needed)."""
    err = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
    v = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", err)
    w, h = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
    return dur, w, h


def is_360(w, h):
    return h > 0 and abs(w / h - 2.0) < 0.05


def _grab(ffmpeg, path, t, vf, size):
    raw = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                          "-vf", vf + f",scale={size[0]}:{size[1]},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    if len(raw) != size[0] * size[1]:
        return None
    return np.frombuffer(raw, np.uint8).reshape(size[1], size[0]).astype(float)


def pick_view(ffmpeg, path, t0, clip_len, avoid_yaws=(), rng=random):
    """Score 8 directions around the 360 scene by movement and light; pick among the best."""
    size = (108, 192)
    scores = []
    for yaw in range(-180, 180, 45):
        if any(abs(((yaw - a + 180) % 360) - 180) < 30 for a in avoid_yaws):
            continue
        vf = f"v360=e:flat:yaw={yaw}:pitch=-8:h_fov={H_FOV:.1f}:v_fov={V_FOV}"
        frames = [_grab(ffmpeg, path, t0 + clip_len * k / 4, vf, size) for k in range(4)]
        frames = [f for f in frames if f is not None]
        if len(frames) < 2:
            continue
        motion = np.mean([np.abs(a - b).mean() for a, b in zip(frames, frames[1:])])
        light = np.mean([f.std() for f in frames])
        scores.append((motion * 2 + light * 0.5, yaw))
    if not scores:
        return rng.choice(range(-180, 180, 45)), -8
    scores.sort(reverse=True)
    yaw = rng.choice(scores[:3])[1] + rng.uniform(-15, 15)   # one of the 3 liveliest, nudged a bit
    return yaw, rng.uniform(-14, -2)


def overlay_png(path, logo_path, fonts_dir, line1, line2, cta):
    """Transparent 1080x1920 layer: dark fades top and bottom, small logo, title text."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = np.zeros((H, W), np.uint8)
    y = np.arange(H)
    top = np.clip(1 - y / 560, 0, 1) ** 1.6 * 170
    bot = np.clip((y - (H - 760)) / 760, 0, 1) ** 1.4 * 215
    a[:] = np.maximum(top, bot).astype(np.uint8)[:, None]
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    shade.putalpha(Image.fromarray(a))
    img = Image.alpha_composite(img, shade)

    logo = Image.open(logo_path).convert("RGBA")
    LW = 360
    logo = logo.resize((LW, int(logo.height * LW / logo.width)), Image.LANCZOS)
    glow = Image.new("RGBA", (logo.width + 120, logo.height + 120), (0, 0, 0, 0))
    glow.paste(logo, (60, 60), logo)
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    glow.putalpha(glow.split()[3].point(lambda v: int(v * 0.6)))
    img.alpha_composite(glow, ((W - glow.width) // 2, 120 - 60))
    img.alpha_composite(logo, ((W - LW) // 2, 120))

    d = ImageDraw.Draw(img)
    fonts_dir = Path(fonts_dir)
    fbold = ImageFont.truetype(str(fonts_dir / "Inter-SemiBold.otf"), 52)
    fmed = ImageFont.truetype(str(fonts_dir / "Inter-Medium.otf"), 42)
    fsm = ImageFont.truetype(str(fonts_dir / "Inter-Medium.otf"), 34)
    for txt, font, yy, al in ((line1, fbold, 1500, 255), (line2, fmed, 1570, 215), (cta, fsm, 1740, 170)):
        tw = d.textlength(txt, font=font)
        d.text(((W - tw) / 2, yy), txt, font=font, fill=(255, 255, 255, al))
    d.line((W / 2 - 90, 1660, W / 2 + 90, 1660), fill=(170, 170, 170, 255), width=3)
    img.save(path)


def render_footage(ffmpeg, video, vstart, audio, astart, dur, out, overlay, yaw=0.0, pitch=-8.0,
                   is360=True, black_and_white=True, seed=0):
    rng = random.Random(seed)
    # render slightly larger than the frame, then drift the crop slowly across it
    mw, mh = W + 96, H + 170
    if is360:
        v_fov = V_FOV * mh / H
        h_fov = math.degrees(2 * math.atan(math.tan(math.radians(v_fov / 2)) * mw / mh))
        frame = f"v360=e:flat:yaw={yaw:.1f}:pitch={pitch:.1f}:h_fov={h_fov:.2f}:v_fov={v_fov:.2f}:w={mw}:h={mh}"
    else:
        frame = f"scale={mw}:{mh}:force_original_aspect_ratio=increase,crop={mw}:{mh}"
    dx, dy = rng.choice([(1, 1), (-1, 1), (1, -1), (-1, -1)])
    cx = f"{(mw - W) / 2}+{dx}*{(mw - W) / 2 - 2}*(t/{dur}-0.5)*2"
    cy = f"{(mh - H) / 2}+{dy}*{(mh - H) / 2 - 2}*(t/{dur}-0.5)*2"
    grade = ",hue=s=0,eq=contrast=1.18:brightness=-0.02" if black_and_white else ",eq=contrast=1.08:saturation=0.85"
    vf = (f"[0:v]fps={FPS},{frame},crop={W}:{H}:x='{cx}':y='{cy}'{grade},"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.8}:d=0.8[bg];"
          f"[bg][2:v]overlay=0:0:format=auto,format=yuv420p[v]")
    cmd = [ffmpeg, "-v", "error", "-y",
           "-ss", f"{vstart:.2f}", "-t", f"{dur}", "-i", str(video),
           "-ss", f"{astart:.2f}", "-t", f"{dur}", "-i", str(audio),
           "-loop", "1", "-t", f"{dur}", "-i", str(overlay),
           "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
           "-af", f"afade=t=in:d=0.5,afade=t=out:st={dur - 1.5}:d=1.5",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed on the footage reel: " + r.stderr[-400:])


def make_footage_reel(ffmpeg, content_dir, state, audio, astart, dur, out, logo_path, fonts_dir,
                      line1, line2, cta, seed):
    """Pick a clip, a random stretch of it and (for 360) the liveliest view; render the reel.
    Returns a short description for the log, or None if there is no usable footage."""
    rng = random.Random(seed)
    clips = find_footage(content_dir)
    usable = []
    for c in clips:
        d, w, h = probe(ffmpeg, c)
        if d >= dur + 4:
            usable.append((c, d, w, h))
    if not usable:
        return None
    fstate = state.setdefault("footage", {})
    # least recently used clip first
    usable.sort(key=lambda u: fstate.get(u[0].name, {}).get("last", 0))
    clip, d, w, h = usable[0] if len(usable) == 1 else rng.choice(usable[:2])
    entry = fstate.setdefault(clip.name, {"used": [], "yaws": []})
    # random start, away from the first/last few seconds and from stretches already used
    for _ in range(40):
        vstart = rng.uniform(2, d - dur - 2)
        if all(abs(vstart - u) > dur for u in entry["used"]):
            break
    three60 = is_360(w, h)
    yaw, pitch = (pick_view(ffmpeg, clip, vstart, dur, entry["yaws"][-3:], rng) if three60 else (0.0, 0.0))
    ov = Path(out).with_suffix(".overlay.png")
    overlay_png(ov, logo_path, fonts_dir, line1, line2, cta)
    render_footage(ffmpeg, clip, vstart, audio, astart, dur, out, ov, yaw, pitch, three60, True, seed)
    ov.unlink(missing_ok=True)
    entry["used"] = (entry["used"] + [round(vstart, 1)])[-30:]
    entry["yaws"] = (entry["yaws"] + [round(yaw)])[-10:]
    import time
    entry["last"] = time.time()
    m, s = divmod(int(vstart), 60)
    return f"{clip.name} @ {m}:{s:02d}" + (f", view {yaw:+.0f} deg" if three60 else "")
