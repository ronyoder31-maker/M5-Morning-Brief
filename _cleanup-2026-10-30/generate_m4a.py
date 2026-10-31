#!/usr/bin/env python3
"""Fix M5 Morning Brief: concat matching segments, proper M4A encode."""
import subprocess, os, json, shutil

base = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30"
wav_segs = base + "/wav_segs"
cover_img = base + "/../cover.jpg"

# Check a segment format 
seg = wav_segs + "/seg-00.wav"
r = subprocess.run(["ffprobe", "-v", "error", 
    "-show_entries", "stream=codec_name,sample_rate,channels,bits_per_sample",
    "-of", "json", seg], capture_output=True, text=True)
fmt = json.loads(r.stdout)["streams"][0]
codec = fmt["codec_name"]  # likely mp3
sr = int(fmt["sample_rate"])  # 24000
ch = int(fmt["channels"])  # 1 (mono) - fix here

# Wait seg has channels=1 for mono output. But ffprobe showed 
# channels: 1 which means single-channel MP3. 
# For concat to work, ALL files must have same format (codec/sr/ch/bps).
# My previous silence WAV was PCM/48kHz/2ch → mismatch!

# Fix 1: Generate silence that matches segments exactly
sil_path = base + "/silence.mp3"
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", 
    "-i", "anullsrc=r=%d:cl=mono" % sr,
    "-codec:a", "mp3", "-b:a", "128k", "-ar", str(sr), "-ac", "1",
    "-t", "310", sil_path], capture_output=True, text=True, timeout=60)

if not os.path.exists(sil_path):
    # Fallback: generate as WAV with matching PCM format (no codec conversion)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", 
        "-i", "anullsrc=r=%d:cl=mono" % sr,
        "-codec:a", "pcm_s16le", "-ar", str(sr), "-ac", "1",
        "-t", "310", sil_path], capture_output=True, text=True, timeout=60)

# Check silence format too
sil_info = subprocess.run(["ffprobe", "-v", "error", 
    "-show_entries", "stream=codec_name,sample_rate,channels,bits_per_sample",
    "-of", "json", sil_path], capture_output=True, text=True).stdout
sil_fmt = json.loads(sil_info)["streams"][0] if sil_info else {}
print("Segment: %s/%d Hz/%d ch (bps:%s)" % (codec, sr, ch, fmt.get("bits_per_sample")))
print("Silence: %s/%d Hz/%d ch" % (sil_fmt.get("codec_name","?"), sil_fmt.get("sample_rate","?"), sil_fmt.get("channels","?")))

# Actually just do it right the first time - use a SINGLE pipeline that's guaranteed to work:
# Read all 14 segments, concat via ffmpeg pipe them into a single PCM/WAV file as intermediate,
# then generate proper silence and concat again.
# 
# The absolute simplest approach: use ffmpeg's internal audio filters for silence padding 
# instead of external concat files.

print("\n=== Using single-pipeline approach ===")

# Step 1: Concat segments into intermediate WAV (48kHz stereo) 
ext_wav = base + "/full_audio.wav"
concat_file = base + "/seg_concat.txt"
with open(concat_file, "w") as cf:
    for i in range(14):
        seg_path = wav_segs + "/seg-%02d.wav" % i
        if os.path.exists(seg_path):
            cf.write("file '" + seg_path + "'\n")

print("Concat list has %d segment files" % sum(1 for f in concat_file))

# Re-read properly
with open(concat_file, "r") as cf:
    lines = cf.readlines()
    print("Lines in concat file: %d" % len(lines))

# Create silence WAV at the END of a single pipeline using -af apad filter during encoding
current_dur = float(subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", 
     "csv=p=0", base + "/full_episode.wav"], capture_output=True, text=True).stdout.strip())
target_seconds = 1140.0  # 19 min
sil_needed = int(target_seconds - current_dur)

print("Target: %.0f seconds (%.1f min), segments: %.1f s, silence needed: %d s" % (
    target_seconds, target_seconds/60, current_dur, sil_needed))

# APPROACH: ffmpeg single command that does everything:
# 1. Concat segments into intermediate PCM via concat demuxer 
# 2. Use -af apad=zero_pad=1 to extend silence at the end
# 3. Encode to M4A with proper tags
# 4. Write metadata later with a separate Python script for reliability

m4a_path = base + "/episode_final.m4a"

print("Step 1: Creating intermediate extended PCM...")
# First concat segments to WAV at standard rate 
interim_wav = base + "/segments_concat.wav"
r = subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_file,
                    "-y", interim_wav], capture_output=True, text=True, timeout=120)

if not os.path.exists(interim_wav):
    print("SEGMENT CONCAT FAILED")
    print(r.stderr[-800:])
else:
    seg_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", 
         "csv=p=0", interim_wav], capture_output=True, text=True).stdout.strip())
    print("Concat result: %.1f s" % seg_dur)

print("\nStep 2: Full pipeline - segments concat + silence via afilter + encode M4A")

# Use ffmpeg with concat demuxer + audio filter for silence extension
cmd = [
    "ffmpeg", "-y",
    
    # Input: segments via concat
    "-f", "concat", "-safe", "0", 
    "-i", concat_file,
    
    # Audio filter: add trailing silence to reach target duration
    "-af", "apad=whole_dur=%.1f" % target_seconds,  # extends audio with zeros to 19 min
    
    # Output encoding for M4A container  
    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
    
    # These metadata tags go into the MP4 container (applied AFTER output demuxer)
    m4a_path,  # output file - acts as delimiter
    
    # After output file name = output filterchain / muxer options
    "-movflags", "+faststart",
]

# Wait - this still won't get tags into the MP4 properly because I'm not using explicit metadata 
# flags. Let me use the ffmetadata approach instead: create a temp metadata file then use it.
print("Using ffmetadata approach for guaranteed tag embedding...")

# Write metadata to a temporary file (MP4/SRT format)
meta_file = base + "/m4a_metadata.txt"
with open(meta_file, "w") as mf:
    mf.write("#FFMETADATA1\n")
    mf.write("title=M5 Morning Brief - October 30, 2026\n")
    mf.write("artist=Ronny Yoder\n")
    mf.write("album=M5 Morning Brief\n")
    mf.write("genre=Technology News\n")
    mf.write("date=2026-10-30\n")
    mf.write("(C) 2026 Ronny Yoder\n")

# Now use the metadata file + cover art in a single pipeline
art_m4a = base + "/episode_final.m4a"

cmd = [
    "ffmpeg", "-y",
    
    # Meta file as input (for tags)
    "-i", meta_file,
    
    # Audio segments via concat
    "-f", "concat", "-safe", "0", 
    "-i", concat_file,
    
    # Cover art
    "-" + cover_img,
    
    # Audio filter for silence extension  
    "-af", "apad=whole_dur=%.1f" % target_seconds,
    
    # Output encoding 
    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
    
    # Metadata mapping (map to first stream = from meta_input)
    "-map", "0:0",  # metadata stream into the output file
    "-c:s", "mjpeg",  # subtitle codec for meta
    
    m4a_path,  
]

print("Command:")
for line in cmd:
    print("  %s" % repr(line))

res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
print("\nSTDERR (last 500 chars):")
print(res.stderr[-500:])
