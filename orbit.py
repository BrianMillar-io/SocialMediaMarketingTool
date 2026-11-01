"""BLCK.MSSV 'orbit' reel look: circular spectrum around the logo, rings that ripple out
on every kick, slow galaxy dust drifting behind."""
import subprocess, math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def render_orbit(ffmpeg, audio, start, dur, logo_path, fonts_dir, out, line1, line2, cta, seed=29):
    start, dur = float(start), float(dur)
    W, H, FPS = 1080, 1920, 30
    N = int(dur * FPS)
    SR = 22050
    rng = np.random.default_rng(seed)
    FONT = str(fonts_dir).rstrip("/") + "/"

    # ---- audio analysis per frame: 64 log-spaced bands + bass + loudness
    raw = subprocess.run([ffmpeg, "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(audio),
                          "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    hop, NF = SR // FPS, 4096
    win = np.hanning(NF)
    freqs = np.fft.rfftfreq(NF, 1 / SR)
    edges = np.geomspace(60, 12000, 65)
    bands, bass, loud = [], [], []
    for i in range(N):
        seg = x[i * hop: i * hop + NF]
        if len(seg) < NF:
            seg = np.pad(seg, (0, NF - len(seg)))
        spec = np.abs(np.fft.rfft(seg * win))
        bands.append([spec[(freqs >= edges[j]) & (freqs < max(edges[j + 1], edges[j] + 6))].mean() + 1e-9 for j in range(64)])
        bass.append(spec[(freqs > 35) & (freqs < 110)].mean())
        loud.append(np.sqrt((seg ** 2).mean()))
    bands = np.log10(np.nan_to_num(np.array(bands), nan=1e-9) + 1e-9)
    bands = (bands - np.percentile(bands, 10, axis=0)) / (np.percentile(bands, 99, axis=0) - np.percentile(bands, 10, axis=0) + 1e-9)
    bands = np.clip(bands, 0, 1)
    def norm(a):
        a = np.array(a); lo, hi = np.percentile(a, 5), np.percentile(a, 98)
        return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)
    bass, loud = norm(bass), norm(loud)
    # smooth bands over time
    sm = np.zeros_like(bands); prev = np.zeros(64)
    for i in range(N):
        prev = np.maximum(bands[i], prev * 0.82); sm[i] = prev
    # kick onsets -> ripple rings
    kick_env = np.zeros(N); k = 0
    onsets = []
    for i in range(N):
        k = max(bass[i], k * 0.80); kick_env[i] = k
        if i > 2 and bass[i] > 0.62 and bass[i] - bass[i - 2] > 0.25 and (not onsets or i - onsets[-1] > 8):
            onsets.append(i)

    # ---- static layers
    cx, cy = W / 2, H * 0.42
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    # galaxy dust band (like the BETA cover), drifting slowly
    def dust_layer():
        big = Image.fromarray((rng.random((90, 50)) * 255).astype(np.uint8)).resize((W + 600, H + 600), Image.BICUBIC)
        big = np.array(big.filter(ImageFilter.GaussianBlur(45)), float) / 255
        fine = Image.fromarray((rng.random((420, 240)) * 255).astype(np.uint8)).resize((W + 600, H + 600), Image.BICUBIC)
        fine = np.array(fine.filter(ImageFilter.GaussianBlur(7)), float) / 255
        Y, X = np.mgrid[0:H + 600, 0:W + 600].astype(float)
        d = (Y - (H + 600) * 1.05 + X * 1.6) / ((H + 600) * 0.55)
        band = np.exp(-(d ** 2) * 6)
        return np.clip(band * (0.3 + big) * (0.4 + fine) * 42, 0, 50)
    dust = dust_layer()
    stars = np.zeros((H, W))
    for _ in range(1100):
        sx_, sy_ = int(rng.uniform(0, W)), int(rng.uniform(0, H))
        stars[sy_, sx_] = 40 + 160 * rng.random() ** 3

    logo = Image.open(logo_path).convert("RGBA")
    LW = 520
    logo = logo.resize((LW, int(logo.height * LW / logo.width)), Image.LANCZOS)
    glow = Image.new("RGBA", (logo.width + 220, logo.height + 220), (0, 0, 0, 0))
    glow.paste(logo, (110, 110), logo)
    glow = glow.filter(ImageFilter.GaussianBlur(30))

    R0 = 395  # inner radius of the spectrum ring
    fbold = ImageFont.truetype(FONT + "Inter-SemiBold.otf", 52)
    fmed = ImageFont.truetype(FONT + "Inter-Medium.otf", 42)
    fsm = ImageFont.truetype(FONT + "Inter-Medium.otf", 34)

    ff = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-ss", str(start), "-t", str(dur), "-i", str(audio),
                           "-af", f"afade=t=in:d=0.5,afade=t=out:st={dur - 1.5}:d=1.5",
                           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19",
                           "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest",
                           "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)

    for f in range(N):
        t = f / FPS
        ox = int(300 + 160 * math.sin(t * 0.07)); oy = int(300 + 220 * math.cos(t * 0.05))
        base = dust[oy:oy + H, ox:ox + W] * (0.75 + 0.35 * loud[f]) + stars
        frame = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGB")

        # ripple rings from recent kicks
        rings = Image.new("L", (W, H), 0)
        rd = ImageDraw.Draw(rings)
        for o in onsets:
            age = (f - o) / FPS
            if 0 <= age < 2.2:
                r = R0 + 40 + age * 420
                a = int(170 * (1 - age / 2.2) ** 1.6)
                rd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=a, width=3)
        rings = rings.filter(ImageFilter.GaussianBlur(1.2))

        # circular spectrum: 128 bars (64 bands mirrored), slowly rotating
        spec = Image.new("L", (W, H), 0)
        sd = ImageDraw.Draw(spec)
        vals = np.concatenate([sm[f], sm[f][::-1]])
        rot = t * 0.08
        for i, v in enumerate(vals):
            ang = rot + 2 * math.pi * i / len(vals) - math.pi / 2
            ln = 6 + 115 * v ** 1.6
            r1, r2 = R0, R0 + ln
            c = int(110 + 145 * v)
            sd.line((cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                     cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)), fill=c, width=5)
        # thin inner circle that breathes with the kick
        rr = R0 - 18 - 6 * kick_env[f]
        sd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=int(90 + 120 * kick_env[f]), width=3)
        spec_glow = spec.filter(ImageFilter.GaussianBlur(10))

        layer = np.array(frame, float)
        for L, gain in ((rings, 1.0), (spec_glow, 0.8), (spec, 1.0)):
            layer = np.maximum(layer, np.array(L, float)[..., None] * gain) if gain == 1.0 else layer + np.array(L, float)[..., None] * gain
        frame = Image.fromarray(np.clip(layer, 0, 255).astype(np.uint8))

        # logo with kick glow
        s = 1.0 + 0.06 * kick_env[f]
        Lg = logo.resize((int(logo.width * s), int(logo.height * s)), Image.BILINEAR)
        G = glow.resize((int(glow.width * s), int(glow.height * s)), Image.BILINEAR)
        G.putalpha(G.split()[3].point(lambda a: int(a * (0.3 + 0.6 * kick_env[f]))))
        frame.paste(G, (int(cx - G.width / 2), int(cy - G.height / 2)), G)
        frame.paste(Lg, (int(cx - Lg.width / 2), int(cy - Lg.height / 2)), Lg)

        d = ImageDraw.Draw(frame)
        for txt, font, y, a in ((line1, fbold, 1500, 255), (line2, fmed, 1570, 200), (cta, fsm, 1740, 150)):
            tw = d.textlength(txt, font=font)
            d.text(((W - tw) / 2, y), txt, font=font, fill=(a, a, a))
        d.line((W / 2 - 90, 1660, W / 2 + 90, 1660), fill=(120, 120, 120), width=3)
        ff.stdin.write(frame.tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed while rendering the orbit reel")
