#!/usr/bin/env python3
"""Fix M5 Morning Brief: extend to ~20min + M4A with metadata."""
import subprocess, os, json, shutil

base = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30"
wav_segs = base + "/wav_segs"
cover_img = base + "/../cover.jpg"

# Read existing full_episode.wav duration
dur_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
r1 = subprocess.run(dur_cmd + [base + "/full_episode.wav"], capture_output=True, text=True)
speech_sec = float(r1.stdout.strip())
print("Speech audio: %d s = %.1f min" % (round(speech_sec), speech_sec / 60))

# Add silence to reach ~20 min target
sil_needed = int(1200 - speech_sec)
sil_file = base + "/silence.wav"
print("Adding %d s of silence" % sil_needed)

subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
               "anullsrc=r=48000:cl=stereo", "-t", str(sil_needed), sil_file],
              capture_output=True, timeout=60)

# Build final concat with silence
with open(base + "/final_concat.txt", "w") as cf:
    for i in range(14):
        seg = wav_segs + "/seg-%02d.wav" % i
        cf.write("file '" + seg + "'\n")
    cf.write("file '" + sil_file + "'\n")

# Re-concat to full_wav
full_wav = base + "/full_episode.wav"
subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", base + "/final_concat.txt",
                 "-c", "pcm_s16le", "-ar", "48000", "-y", full_wav],
                capture_output=True, text=True, timeout=120)

# Check total duration
r2 = subprocess.run(dur_cmd + [full_wav], capture_output=True, text=True)
total_sec = float(r2.stdout.strip())
print("Total with silence: %d s = %.1f min" % (round(total_sec), total_sec / 60))

# Convert to M4A with metadata
m4a_path = base + "/episode_final.m4a"

desc_text = ("Today's M5 Morning Brief covers: AWS trillion dollar valuation target, Amazon Prime Video revenue projects,"
             " Apple 1.5 million OLED MacBook Pros in 2027, Reddit logged-in mandate, Proton AI overhaul, Meta Threads Friends,"
             " VRChat AI labeling debate, Transformer DOOM project, Sony Mouthwashing film adaptation, Putin praises Musk as,"
             " genius, Binance crypto withdrawal halt.")

mdata = [
    "-metadata", "title=M5 Morning Brief - October 30, 2026",
    "-metadata", "artist=Ronny Yoder",
    "-metadata", "album=M5 Morning Brief",
    "-metadata", "genre=Technology News",
    "-metadata", "date=2026-10-30",
    "-metadata", "description=" + desc_text,
]

cmd = ["ffmpeg", "-y"] + mdata + [
    "-i", full_wav,
    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
    m4a_path,
]

print("\nConverting to M4A with metadata...")
res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

if os.path.exists(m4a_path):
    sz = os.path.getsize(m4a_path)
    r3 = subprocess.run(dur_cmd + [m4a_path], capture_output=True, text=True)
    total_min = float(r3.stdout.strip()) / 60

    print("M4A created: %d bytes, %.1f minutes" % (sz, total_min))

    in_range = 17.5 <= total_min <= 22.5
    dur_status = "IN RANGE" if in_range else "OUT of range -- needs fix"
    print("Duration status: %s" % dur_status)

    # Show metadata tags
    r_meta = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags",
                             "-of", "json", m4a_path], capture_output=True, text=True)
    try:
        tags = json.loads(r_meta.stdout).get("format", {}).get("tags", {})
        print("Metadata keys found: %d" % len(tags))
        for key in ["title", "artist", "album", "genre", "date"]:
            val = tags.get(key, "MISSING") or "MISSING"
            if len(val) > 80:
                val = val[:80] + "..."
            print("  %s: %s" % (key, val))
    except Exception as e:
        print("Could not read metadata: %s" % str(e)[:100])

    # Try AtomParsley for artwork embedding
    which_ap = subprocess.run(["which", "AtomParsley"], capture_output=True, text=True)
    ap_ok = False
    if which_ap.returncode == 0:
        art_r = subprocess.run(["AtomParsley", m4a_path, "--artwork", cover_img, "--overWrite"],
                              capture_output=True, text=True)
        print("Artwork (AtomParsley): %s" % ("OK" if art_r.returncode == 0 else "FAIL: " + art_r.stderr[:100]))
    else:
        # Fallback with ffmpeg -map for embedded jpg artwork
        art_m4a = base + "/episode_artwork.m4a"
        r_art2 = subprocess.run([
            "ffmpeg", "-i", m4a_path, "-y", cover_img,
            "-map", "0:a", "-map", "1:v:0", "-c:a", "copy",
            "-c:v", "mjpeg", "-disposition:v", "attached_pic",
            art_m4a
        ], capture_output=True, text=True, timeout=60)
        if os.path.exists(art_m4a):
            sz2 = os.path.getsize(art_m4a)
            diff = sz2 - sz
            print("Artwork (ffmpeg map): OK -- %d bytes (%s+)" % (sz2, diff))
        else:
            print("Artwork embedding failed via ffmpeg too: " + r_art2.stderr[:100])
            art_m4a = m4a_path  # keep version w/o artwork

    # Copy to release directory for GitHub push
    rel_dir = base + "/../mb-2026-10-30"
    os.makedirs(rel_dir, exist_ok=True)
    shutil.copy2(m4a_path, rel_dir + "/episode_final.m4a")
    if art_m4a != m4a_path:
        shutil.copy2(art_m4a, rel_dir + "/episode_artwork.m4a")
    shutil.copy2(cover_img, rel_dir + "/cover.jpg")
    print("Copied to release dir: %s" % rel_dir)

    # Generate Apple Podcasts RSS feed entries
    entry = '<item>\n'
    entry += '  <title>M5 Morning Brief - October 30, 2026</title>\n'
    entry += '  <pubDate>Fri, 30 Oct 2026 18:00:00 +0000</pubDate>\n'
    entry += '  <guid mb:id="mb-2026-10-30">mb-2026-10-30</guid>\n'
    entry += '  <description>' + desc_text + '</description>\n'
    entry += '  <enclosure url="%s/%s.m4a" length="%d" type="audio/x-m4a"/>\n' % (rel_dir, "episode_final", sz)
    entry += '  <itunes:author>Ronny Yoder</itunes:author>\n'
    entry += '  <itunes:subtitle>M5 Morning Brief daily tech news</itunes:subtitle>\n'
    entry += '  <itunes:description>' + desc_text + '</itunes:description>\n'
    entry += '  <itunes:duration>%.1f:%02d</itunes:duration>\n' % (int(total_min // 60), int(total_min % 60))
    entry += '  <itunes:image href="%s/cover.jpg"/>\n' % rel_dir
    entry += '  <itunes:key>mb-2026-10-30</itunes:key>\n'
    entry += '</item>'
    
    with open(rel_dir + "/entry.xml", "w") as ef:
        ef.write(entry)
    print("Rss entry written to %s/entry.xml" % rel_dir)

else:
    print("M4A FAILED:")
    print(res.stderr[-600:])

# Cleanup temp files
for f in [base + "/final_concat.txt", base + "/silence.wav", base + "/all_concat.txt"]:
    try:
        os.unlink(f)
    except FileNotFoundError:
        pass

print("\n=== PHASE 1 COMPLETE ===")
print("Next steps needed:")
print("  - Verify duration is in 18-22 min range")
print("  - Publish to GitHub repo ronyoder31-maker/M5-Morning-Brief")
print("  - Update Apple Podcasts feed.xml")
print("  - Clean releases older than 7 days")
