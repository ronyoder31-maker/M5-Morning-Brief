#!/usr/bin/env python3
"""Encode extended_full.wav → M4A, add tags/artwork, prepare release."""
import subprocess, os, json, shutil

base = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30"
cover_img = base + "/../cover.jpg"

# Step 1: Encode M4A (no tags yet)
m4a_clean = base + "/episode_clean.m4a"
res = subprocess.run([
    "ffmpeg", "-y", "-i", base + "/extended_full.wav",
    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
    "-movflags", "+faststart",
    m4a_clean], capture_output=True, text=True, timeout=300)

if not os.path.exists(m4a_clean):
    print("FFMPEG FAIL:", res.stderr[-500:])
    exit(1)

sz = os.path.getsize(m4a_clean)
dur = float(subprocess.run(
    ["ffprobe", "-v","error","-show_entries","format=duration","-of",
     "csv=p=0", m4a_clean], capture_output=True, text=True).stdout.strip())

print("M4A %d bytes (%.1f MB), %.1f min" % (sz, sz/1048576, dur/60))
in_range = 17.5 <= dur/60 <= 22.5
print("In range: %s" % ("YES" if in_range else "NO"))

# Step 2: Add metadata with ffmpeg - put tags as muxing options BEFORE output filename
# For mp4, use -metadata_key=value syntax (single flag) or repeated -metadata
m4a_tagged = base + "/episode_tagged.m4a"

tags = [
    ("title", "M5 Morning Brief - October 30, 2026"),
    ("artist", "Ronny Yoder"),
    ("album", "M5 Morning Brief"), 
    ("genre", "Technology News"),
    ("date", "2026-10-30"),
    ("copyright", "(C) 2026 Ronny Yoder"),
]

tag_args = []
for k, v in tags:
    tag_args.extend(["-metadata", "%s=%s" % (k, v)])

print("\nTag command args (last portion):")
cmd = [
    "ffmpeg", "-y", 
    "-i", m4a_clean,
] + tag_args + [m4a_tagged]

for a in cmd[-10:]:
    print("  %s" % repr(a))

res2 = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print("\nM4A with tags result: %d bytes" % (os.path.getsize(m4a_tagged) if os.path.exists(m4a_tagged) else 0))
if res2.returncode != 0:
    print("ERROR:", res2.stderr[-500:])

# Step 3: Verify tags
r_meta = subprocess.run(["ffprobe", "-v","error","-show_entries","format_tags","-of","json",
                          m4a_tagged], capture_output=True, text=True)
try:
    tags_found = json.loads(r_meta.stdout).get("format",{}).get("tags",{})
    print("\nFound %d tags:" % len(tags_found))
    for k in ["title","artist","album","genre","date","copyright"]:
        v = tags_found.get(k, "MISSING") or "MISSING"
        if len(v)>50: v=v[:50]+"..."
        print("  %-10s %s" % (k+":", v))
except Exception as e:
    print("Tag read error:", str(e)[:200])

# Step 4: Embed artwork via AtomParsley or ffmpeg -map approach
art_m4a = base + "/episode_final.m4a"
cover_done = False

r_atoms = subprocess.run(["which", "AtomParsley"], capture_output=True, text=True)
if r_atoms.returncode == 0:
    r_ap = subprocess.run(["AtomParsley", m4a_tagged, "--artwork", cover_img, "--overWrite"],
                           capture_output=True, text=True)
    if r_ap.returncode == 0:
        shutil.copy2(m4a_tagged, art_m4a)
        print("\nCover via AtomParsley: OK")
        cover_done = True

if not cover_done:
    # ffmpeg attachment method
    r_art = subprocess.run([
        "ffmpeg", "-y", "-i", m4a_tagged,
        "-i", cover_img,
        "-map", "0:a:0", "-map", "1:v:0",
        "-c:a", "copy", "-c:v", "mjpeg", 
        "-disposition:v", "attached_pic",
        art_m4a], capture_output=True, text=True, timeout=60)
    
    if os.path.exists(art_m4a):
        sz_art = os.path.getsize(art_m4a)
        dur_art = float(subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0", art_m4a],
            capture_output=True, text=True).stdout.strip())
        print("Cover via ffmpeg: OK (%d bytes, %.1f min)" % (sz_art, dur_art/60))
        cover_done = True
    else:
        # fallback - just copy as-is  
        shutil.copy2(m4a_tagged, art_m4a)
        print("\nNo cover tool available; using audio-only M4A")

# Step 5: Prepare release directory
rel_dir = base + "/../mb-2026-10-30"
os.makedirs(rel_dir, exist_ok=True)

final_file = art_m4a if os.path.exists(art_m4a) else m4a_tagged
shutil.copy2(final_file, rel_dir + "/episode_final.m4a")
if os.path.exists(cover_img):
    shutil.copy2(cover_img, rel_dir + "/cover.jpg")

# Step 6: Apple Podcasts feed.xml content 
dm = int(dur // 60)
ds = int(dur % 60)

entry_xml = (
    '<item>'
    + '<title>M5 Morning Brief - October 30, 2026</title>'
    + '<pubDate>Fri, 30 Oct 2026 18:00:00 +0000</pubDate>'
    + '<link>https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/tag/mb-2026-10-30</link>'
    + '<guid mb:id="mb-2026-10-30" isPermaLink="false">mb-2026-10-30</guid>'
    + '<description>Today'"'"'s M5 Morning Brief covers: AWS targeting a trillion-dollar valuation, '
    + 'Amazon Prime Video revenue projections, Apple shipping 1.5M OLED MacBook Pros in 2027, '
    + 'Reddit logged-in mandate shift, Proton AI privacy overhaul, Meta Threads Friends testing, '
    + 'VRChat AI labeling decision, Transformer DOOM benchmarks, Sony Mouthwashing adaptation, '
    + 'Putin-Musk dynamics, Binance volatility.</description>'
    + '<enclosure url="https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/mb-2026-10-30/episode_final.m4a" '
      'length="%d" type="audio/x-m4a"/>' % sz
    + '<itunes:author>Ronny Yoder</itunes:author>'
    + '<itunes:subtitle>Daily tech news deep dive</itunes:subtitle>'
    + '<itunes:description>Today'"'"'s M5 Morning Brief covers: AWS targeting a trillion-dollar valuation, '
    + 'Amazon Prime Video revenue projections, Apple shipping 1.5M OLED MacBook Pros in 2027, '
    + 'Reddit logged-in mandate shift, Proton AI privacy overhaul, Meta Threads Friends testing, '
    + 'VRChat AI labeling decision, Transformer DOOM benchmarks, Sony Mouthwashing adaptation, '
    + 'Putin-Musk dynamics, Binance volatility.</itunes:description>'
    + '<itunes:duration>%d:%02d</itunes:duration>' % (dm, ds)
    + '<itunes:image href="https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/mb-2026-10-30/cover.jpg"/>'
    + '<itunes:key>mb-2026-10-30</itunes:key>'
    + '</item>'
)

with open(rel_dir + "/entry.xml", "w") as ef:
    ef.write(entry_xml)

print("\n=== M4A PRODUCTION COMPLETE ===")
print("Episode file:   %s" % final_file)
print("Release dir:    %s" % rel_dir)
print("Duration:       %.1f min (%d:%02d)" % (dur/60, dm, ds))
print("Size:           %d bytes (%.1f MB)" % (sz, sz/1048576))

# Cleanup temporary files
for f in [m4a_clean, m4a_tagged, base + "/extended_full.wav", 
          base + "/seg_concat.txt", base + "/silence.mp3",
          base + "/silence_extended.mp3"]:
    try: os.unlink(f)
    except FileNotFoundError: pass
