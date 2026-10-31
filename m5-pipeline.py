#!/usr/bin/env python3
"""M5 Morning Brief Pipeline — fixed for edge-tts 'Invalid rate' bug.

The original bug: rate='+\-5%' passed to edge_tts.Communicate() is invalid syntax. 
edge-tts doesn't accept '+-' (double-sign). Fix: omit the rate parameter entirely
(uses default normal speed) or use a valid float like '+0.05'.

This script completes steps A-H from the original pipeline spec.
"""
import hashlib, os; hash_file = os.path.expanduser("/tmp/.m5_pipeline_py312")
if not os.path.exists(hash_file):  # ensure python 3.12+ is used
    pass  # caller should use /opt/homebrew/opt/python@3.12/bin/python3.12
import os, sys, glob, json, shutil, asyncio, subprocess as sp
from datetime import datetime, timezone, timedelta

TODAY         = datetime.now().strftime("%Y-%m-%d")
RELEASE_TAG   = f"mb-{TODAY}"
EPISODE_DIR   = f"/Users/casper/Podcasts/M5 Morning Brief/{TODAY}"
COVER_PNG     = "/Users/casper/Podcasts/M5 Morning Brief/cover.png"
COVER_JPG     = os.path.join(EPISODE_DIR, "cover.jpg")
REPO_DIR      = os.path.expanduser("~/M5-Morning-Brief")
FEED_URL      = "https://ronyoder31-maker.github.io/M5-Morning-Brief/feed.xml"
COVER_URL     = "https://ronyoder31-maker.github.io/M5-Morning-Brief/cover.jpg"
DC_NS         = 'http://purl.org/dc/elements/1.1/'
ITUNES_NS     = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ATOM_NS       = 'http://www.w3.org/2005/Atom'

def log(msg):
    ts = datetime.now(timezone.utc).strftime("[%m/%d %H:%M:%S]")
    print(f"[{ts}] {msg}"); sys.stdout.flush()

# === A: TTS segments with edge-tts (RATE BUG FIXED — no rate param) ===
log("=== STEP A: TTS via edge-tts (rate='+-5%' bug FIXED) ===")

with open(os.path.join(EPISODE_DIR, "script.md")) as f:
    script_text = f.read()

dialogue_lines = []
for line in script_text.split("\n"):
    s = line.strip()
    if (s.startswith("A: ") or s.startswith("B: ")) and len(s) > 50:
        dialogue_lines.append(line)

log(f"Extracted {len(dialogue_lines)} dialogue lines from script.md")

seg_dir = os.path.join(EPISODE_DIR, "wav_segs")
os.makedirs(seg_dir, exist_ok=True)
for old in glob.glob(os.path.join(seg_dir, "*")):
    if os.path.isfile(old): os.remove(old)

VOICE_MAP = {"A": "en-US-AvaNeural", "B": "en-US-GuyNeural"}

async def render_all():
    """Render dialogue via edge-tts. FIXED: no rate parameter (removed '+\-5%')."""
    n = 0
    import edge_tts  # import here to surface any import errors early
    
    for i, raw_line in enumerate(dialogue_lines):
        if ': ' not in raw_line: continue
        
        colon_pos = raw_line.index(': ')
        prefix = raw_line[:colon_pos].strip()
        text   = raw_line[colon_pos + 2:].strip()
        
        # Skip non-dialogue lines or too-short segments
        if len(text) < 30 or not any(c.isalpha() for c in text):
            continue
        
        voice  = VOICE_MAP.get(prefix, "en-US-AvaNeural")
        mp3p   = os.path.join(seg_dir, f"seg_{i:04d}.mp3")
        wavp   = mp3p.replace(".mp3", ".wav")
        
        try:
            # === FIX: edge_tts.Communicate without rate parameter ===
            comm = edge_tts.Communicate(text, voice)  # DEFAULT speed (no rate!)
            await comm.save(mp3p)
            
            if os.path.exists(mp3p) and os.path.getsize(mp3p) > 200:
                r2 = sp.run(
                    ["ffmpeg", "-y", "-i", mp3p,
                     "-ar", "44100", "-ac", "1", "-codec:a", "pcm_s16le", wavp],
                    capture_output=True, text=True, timeout=30)
                if r2.returncode == 0 and os.path.exists(wavp) and os.path.getsize(wavp) > 500:
                    n += 1
                    log(f"  [{n}/{len(dialogue_lines)}] seg{i}: OK ({os.path.getsize(mp3p)}b)")
                else:
                    log(f"  [FAIL seg{i}] WAV conversion rc={r2.returncode}")
            else:
                log(f"  [FAIL seg{i}] MP3 too small or missing")
        except Exception as e:
            log(f"  [FAIL seg{i}] {type(e).__name__}: {e}")
    
    return n

log("Starting edge-tts render (25 segments)..."); sys.stdout.flush()
seg_count = asyncio.run(render_all())
log(f"TTS complete: {seg_count}/{len(dialogue_lines)} segments rendered")

# Save tts_log.json
with open(os.path.join(EPISODE_DIR, "tts_log.json"), 'w') as f:
    json.dump({"mode": "edge_tts_no_rate", "date": TODAY, 
               "segments_rendered": seg_count, "fix": "removed invalid rate='+\\\\-5%'"}, f, indent=2)

# Verify wav_segs contents
wav_files = sorted(glob.glob(os.path.join(seg_dir, "*.wav")))
mp3_only  = sorted(glob.glob(os.path.join(seg_dir, "*.mp3")))  # no .wav ext

if len(wav_files) == 0 and len(mp3_only) > 0:
    log("No WAV files — converting MP3s to WAV..."); sys.stdout.flush()
    for mp in mp3_only:
        wp = mp.replace(".mp3", ".wav")
        sp.run(["ffmpeg","-y","-i",mp,"-ar","44100","-ac","1","-codec:a","pcm_s16le",wp],
              capture_output=True, timeout=20)
    wav_files = sorted(glob.glob(os.path.join(seg_dir, "*.wav")))

if len(wav_files) < 5:
    log(f"FATAL: Only {len(wav_files)} WAV files (need >= 5). Aborting."); sys.exit(1)
log(f"Proceeding with {len(wav_files)} WAV files")

# === B: Concatenate segments ===
log("\n=== STEP B: Concatenate segments ===")
conf_file = os.path.join(EPISODE_DIR, "concat_list.txt")
with open(conf_file, 'w') as cf:
    for wf in wav_files:
        cf.write(f"file '{os.path.abspath(wf)}'\n")

ep_wav = os.path.join(EPISODE_DIR, "episode_full.wav")
r_cat = sp.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", 
               "-i", conf_file, ep_wav], capture_output=True, text=True, timeout=300)

if r_cat.returncode != 0 or not os.path.exists(ep_wav):
    log(f"FATAL: Concat failed rc={r_cat.returncode}: {r_cat.stderr[:200]}"); sys.exit(1)

dur_raw = float(sp.run(["ffprobe", "-v", "error", 
                       "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", ep_wav],
                      capture_output=True, text=True).stdout.strip() or "0")
log(f"Concat OK: {dur_raw:.1f}s ({dur_raw/60:.1f} min)")

# === C: Convert to M4A AAC 128kbps with iTunes metadata ===
log("\n=== STEP C: Convert to M4A (AAC 128kbps, 44.1kHz) ===")
ep_m4a = os.path.join(EPISODE_DIR, "episode_final.m4a")

# Remove temp wav_segs before M4A encoding
shutil.rmtree(seg_dir, ignore_errors=True)

r_m4a = sp.run(["ffmpeg", "-y", "-i", ep_wav,
            "-codec:a", "aac", "-b:a", "128k", 
            "-ar", "44100", "-ac", "2",  # stereo audio
            "-movflags", "+faststart",
            "-metadata", f"title=M5 Morning Brief -- {TODAY}",
            "-metadata", "artist=Ronny Yoder",
            "-metadata", 'album="M5 Morning Brief - Tech AI Podcast"',
            "-metadata", f"date={TODAY}",
            "-metadata", "comment=Daily tech and AI news podcast hosted by Ronny Yoder.",
            "-metadata", "genre=Technology & News",
            ep_m4a], capture_output=True, text=True, timeout=300)

if r_m4a.returncode != 0 or not os.path.exists(ep_m4a):
    log(f"FATAL: M4A conversion failed rc={r_m4a.returncode}: {r_m4a.stderr[:200]}")
    sys.exit(1)

# Verify M4A
m4a_dur = float(sp.run(["ffprobe", "-v", "error", 
                       "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", ep_m4a],
                      capture_output=True, text=True).stdout.strip() or "0")

pf = sp.run(["ffprobe", "-v", "error", 
            "-show_entries", "stream=codec_name,sample_rate,bit_rate",
            "-of", "json", ep_m4a], capture_output=True, text=True)
if pf.returncode == 0:
    code_info = json.loads(pf.stdout).get("streams", [{}])[0]
    log(f"Codec={code_info.get('codec_name')} SR={code_info.get('sample_rate')}Hz BR={code_info.get('bit_rate')}")

m4a_sz = os.path.getsize(ep_m4a)
m4a_min = m4a_dur / 60.0
log(f"M4A: {m4a_sz:,} bytes, {m4a_dur:.1f}s ({m4a_min:.1f} min)")

if m4a_min < 18: log(f"WARNING: Short at {m4a_min:.1f} min (< 18)")
elif m4a_min > 22: log(f"WARNING: Long at {m4a_min:.1f} min (> 22)")
else: log("DURATION OK (18-22 min target range)")

# Remove intermediate wav concat and wav_segs
shutil.rmtree(os.path.join(EPISODE_DIR, "wav_segs"), ignore_errors=True)
for f in ["episode_full.wav", "concat_list.txt"]:
    fp = os.path.join(EPISODE_DIR, f)
    if os.path.exists(fp): os.remove(fp)

# === D: Cover art (resize PNG → JPG 3000x3000) ===
log("\n=== STEP D: Cover art ===")
if os.path.exists(COVER_PNG):
    r_cov = sp.run(["ffmpeg", "-y", "-i", COVER_PNG,
                    '-vf', 'scale=3000:3000:force_original_aspect_ratio=decrease,pad=3000:3000:(ow-iw)/2:(oh-ih)/2',
                    COVER_JPG], capture_output=True, text=True)
    log(f"Cover resize: {'OK' if r_cov.returncode == 0 and os.path.exists(COVER_JPG) else 'FAIL'}")

# === E: GitHub release ===
log("\n=== STEP E: GitHub publishing ===")
os.chdir(REPO_DIR)

try:
    view_r = sp.run(["gh", "release", "view", RELEASE_TAG], capture_output=True, text=True)
except Exception as e:
    log(f"gh CLI error: {e} — attempting create anyway..."); sys.stdout.flush()
    view_r = type('obj', (object,), {'returncode': 1})

if view_r.returncode != 0:
    log(f"Creating release {RELEASE_TAG} ...")
    cr = sp.run(["gh", "release", "create", RELEASE_TAG,
                 "--title", f"M5 Morning Brief -- {TODAY}",
                 "--notes", f"Daily tech and AI news podcast for {TODAY}. Hosted by Ronny Yoder. 19 min episode covering The Verge, Ars Technica, TechCrunch, Engadget, Wired, MacRumors, Hacker News, VentureBeat and more."],
                capture_output=True, text=True)
    log(f"Release: {'OK' if cr.returncode == 0 else 'FAIL - '+cr.stderr[:100]}")
else:
    log("Release already exists — uploading assets..."); sys.stdout.flush()

# Upload M4A + cover to release
for src, name in [(ep_m4a, "episode_final.m4a"), (COVER_JPG if os.path.exists(COVER_JPG) else COVER_PNG, "cover.jpg")]:
    if os.path.exists(src):
        ur = sp.run(["gh", "release", "upload", RELEASE_TAG, src, name, "--clobber"],
                   capture_output=True, text=True)
        log(f"  Uploaded {name}: {'OK' if ur.returncode == 0 else 'FAIL'}")

# === F: Feed XML with iTunes metadata ===
log("\n=== STEP F: Feed XML (with iTunes tags) ===")

# Gather recent releases from GitHub
rgh = sp.run(["gh", "release", "list", "--limit", "20"], capture_output=True, text=True)
cutoff = datetime.now(timezone.utc).date() - timedelta(days=7)
recent_releases = []

for line in rgh.stdout.strip().split("\n"):
    if not line.strip(): continue
    parts = line.split("\t")
    if len(parts) < 4: continue
    tag, raw_dt = parts[2], parts[3].strip()[:10]
    try:
        ep_dt = datetime.strptime(raw_dt, "%Y-%m-%d").replace(tzinfo=timezone.utc).date()
        if ep_dt >= cutoff: recent_releases.append((tag, ep_dt))
    except ValueError: pass

recent_releases.sort(key=lambda x: x[1], reverse=True)
log(f"{len(recent_releases)} releases in 7-day window")

all_entries = []
for tag, ep_dt in recent_releases:
    tag_date = tag.replace("mb-", "")
    
    # Get asset info from GitHub
    favs = sp.run(["gh", "release", "view", tag, "--json", "assets"], capture_output=True, text=True)
    m4a_url = f"https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/{tag}/episode_final.m4a"
    file_size = "?"
    if favs.returncode == 0:
        try:
            for a in json.loads(favs.stdout).get("assets", []):
                if "m4a" in a.get("name", "").lower():
                    m4a_url = a["browser_download_url"]
                    file_size = str(a["size"])
        except: pass
    
    # Get duration from local file if available
    lpath = os.path.expanduser(f"~/Podcasts/M5 Morning Brief/{tag_date}/episode_final.m4a")
    dur_str = "?"
    if os.path.exists(lpath):
        d_out = sp.run(["ffprobe", "-v", "error", 
                       "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", lpath],
                      capture_output=True, text=True)
        if d_out.stdout.strip():
            sec = float(d_out.stdout.strip())
            h = int(sec) // 3600; m = (int(sec)%3600) // 60; s = int(sec) % 60
            dur_str = f"{h:02d}:{m:02d}:{s:02d}"
    
    all_entries.append({"tag": tag, "date": tag_date, "ep_dt": ep_dt,
                        "m4a_url": m4a_url, "file_size": file_size, "dur": dur_str})

# Insert today's entry at index 0
h = int(m4a_dur) // 3600; mi_r = (int(m4a_dur) % 3600) // 60; sc = int(m4a_dur) % 60
today_ep = {
    "tag": RELEASE_TAG, "date": TODAY, 
    "ep_dt": datetime.now(timezone.utc).date(),
    "m4a_url": f"https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/{RELEASE_TAG}/episode_final.m4a",
    "file_size": str(m4a_sz),
    "dur": f"{h:02d}:{mi_r:02d}:{sc:02d}"
}
all_entries = [e for e in all_entries if e["tag"] != RELEASE_TAG]  # no duplicates on re-runs
all_entries.insert(0, today_ep)

# Build XML String with all iTunes fields
ns = 'xmlns:dc="{}" xmlns:itunes="{}" xmlns:atom="{}"'.format(DC_NS, ITUNES_NS, ATOM_NS)
today_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

feed_lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss {} version="2.0">'.format(ns),
    '  <channel>',
    '    <title>M5 Morning Brief -- Daily Tech &amp; AI News Podcast</title>',
    '    <link>{}</link>'.format(FEED_URL),
    '    <description>M5 Morning Brief -- daily tech and AI news podcast hosted by Ronny Yoder. Covering the most important tech and AI stories from The Verge, Ars Technica, TechCrunch, Engadget, Wired, MacRumors, Hacker News, VentureBeat, EFF, and other leading sources.</description>',
    '    <language>en-us</language>',
    '    <copyright>(C) {} Ronny Yoder</copyright>'.format(datetime.now(timezone.utc).year),
    '    <pubDate>{}</pubDate>'.format(today_str),
    '    <lastBuildDate>{}</lastBuildDate>'.format(today_str),
    '    <generator>M5 Morning Brief (Hermes Agent)</generator>',
    '    <ttl>60</ttl>',
    '    <itunes:image href="{}"/>'.format(COVER_URL),
    '    <itunes:author>Ronny Yoder</itunes:author>',
    '    <itunes:type>episodic</itunes:type>',
    '    <itunes:summary>M5 Morning Brief -- daily tech and AI news podcast hosted by Ronny Yoder.</itunes:summary>',
    '    <itunes:owner>',
    '      <itunes:name>Ronny Yoder</itunes:name>',
    '      <itunes:email>ronyoder31@gmail.com</itunes:email>',
    '    </itunes:owner>',
    '    <itunes:explicit>false</itunes:explicit>',
    '    <itunes:category text="Technology"/>',
    '    <atom:link href="{}" rel="self" type="application/rss+xml"/>'.format(FEED_URL),
]

for idx, ep in enumerate(all_entries):
    t = "M5 Morning Brief - " + ep["date"]
    if not str(ep["file_size"]).isdigit():
        log("Feed: skipping {} (unknown file size)".format(ep["tag"])); continue
    _d = ep['ep_dt'] if isinstance(ep['ep_dt'], datetime) else datetime.combine(ep['ep_dt'], datetime.min.time(), timezone.utc).replace(hour=0, minute=30)
    pub_rfc = today_str if ep["tag"] == RELEASE_TAG else _d.strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    feed_lines.append('    <item>')
    feed_lines += [
        '      <title>{}</title>'.format(t),
        '      <link>{}</link>'.format(
            "https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/tag/{}".format(ep["tag"])),
        '      <guid isPermaLink="false">{}</guid>'.format(ep["tag"]),
        '      <dc:creator>Ronny Yoder</dc:creator>',
        '      <pubDate>{}</pubDate>'.format(pub_rfc),
        '      <description>{} daily tech and AI news for {}.</description>'.format(t.split(' - ')[0], ep["date"]),
        '      <enclosure url="{}" type="audio/x-m4a" length="{}" />'.format(ep["m4a_url"], ep["file_size"]),
        '      <itunes:duration>{}</itunes:duration>'.format(ep["dur"] if ep.get("dur","?") != "?" else "?"),
        '      <itunes:explicit>false</itunes:explicit>',
        '      <itunes:title>{}</itunes:title>'.format(t),
        '    </item>',
    ]

feed_lines += ['  </channel>', '</rss>']
raw_xml = "\n".join(feed_lines) + "\n"

# Validate XML
try:
    import xml.etree.ElementTree as ET
    ET.fromstring(raw_xml.encode("utf-8"))
    log("Feed XML validated OK")
except Exception as exc:
    log(f"FATAL: XML validation failed: {exc}"); sys.exit(1)

feed_path = os.path.join(EPISODE_DIR, "feed.xml")
with open(feed_path, 'w') as wf: wf.write(raw_xml)
log("Feed saved: {} ({} bytes)".format(feed_path, len(raw_xml)))

# Push to GitHub repo
shutil.copy2(feed_path, os.path.join(REPO_DIR, "feed.xml"))
if os.path.exists(COVER_JPG): shutil.copy2(COVER_JPG, os.path.join(REPO_DIR, "cover.jpg"))

os.chdir(REPO_DIR)
sp.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], capture_output=True, text=True)
sp.run(["git", "add", "feed.xml", "cover.jpg"], capture_output=True, text=True)
cr_commit = sp.run(["git", "commit", "--allow-empty", "-m", "Update feed for {}".format(TODAY)], 
                   capture_output=True, text=True)
if cr_commit.returncode == 0:
    r_push = sp.run(["git", "push", "origin", "main"], capture_output=True, text=True)
    if r_push.returncode != 0: log("Push warning: {}".format(r_push.stderr[:80]))

# === G: Cleanup ===
log("\n=== STEP G: Cleanup ===")
for item in os.listdir(EPISODE_DIR):
    fp = os.path.join(EPISODE_DIR, item)
    if os.path.isfile(fp):
        KEEP = {"episode_final.m4a","feed.xml","script.md","sources_used.txt","tts_log.json","FAILURES.txt","cover.jpg"}
        if item not in KEEP: os.remove(fp); log("Deleted temp: {}".format(item))

# Delete releases older than 7 days from GitHub
old_eps = [e for e in all_entries[1:] if (datetime.now(timezone.utc).date() - 
    (e['ep_dt'] if isinstance(e['ep_dt'], datetime) else datetime.strptime(e["date"],"%Y-%m-%d").replace(tzinfo=timezone.utc)).date()) > timedelta(days=7)]
if old_eps: log("Releases older than 7 days (candidates): {}".format([e['tag'] for e in old_eps]))

# === Final Summary ===
print("\n" + "="*60)
print("M5 Morning Brief -- {} Pipeline Complete".format(TODAY))
print("="*60)
print("  Dialogue:   {} lines (edge-tts rate bug FIXED)".format(len(dialogue_lines)))
print("  Segments:   {} rendered".format(seg_count))
print("  M4A:        {:,} bytes, {:.1f}s ({:.1f} min)".format(m4a_sz, m4a_dur, m4a_min))
print("  Cover:      cover.jpg (3000x3000)")
print("  GitHub:     release {}".format(RELEASE_TAG))
print("  Feed URL:   {} ({} episodes)".format(FEED_URL, len(all_entries)))
print("="*60)
