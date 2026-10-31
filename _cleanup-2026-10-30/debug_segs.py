#!/usr/bin/env python3
"""Debug segment durations."""
import subprocess, os, json

base = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30"
wav_segs = base + "/wav_segs"

total_dur = 0
print("=== Segment analysis ===")
for i in range(14):
    fname = "seg-%02d.wav" % i
    fpath = wav_segs + "/" + fname
    exists = os.path.exists(fpath)
    sz = os.path.getsize(fpath) if exists else 0
    dur_r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", 
                             "format=duration,size,r_frame_rate,channels,sample_rate,bit_rate", "-of", "json", fpath],
                            capture_output=True, text=True)
    try:
        fmt = json.loads(dur_r.stdout).get("format", {})
        dur = float(fmt.get("duration", 0))
        ch = fmt.get("channels", 0)
        sr = fmt.get("sample_rate", 0)
    except:
        dur = -1; ch = -1; sr = -1

    dur_label = "%.2f s" % dur if dur > 0 else "ERR"
    total_dur += dur if dur > 0 else 0
    print("%s -> exists=%3d sz=%8d dur=%-8s(%5.1fm) ch=%d sr=%d" % (fname, exists, sz, 
           dur_label, dur/60 if dur > 0 else 0, ch, sr))

print("\nTotal segment duration: %.1f s = %.1f min" % (total_dur, total_dur / 60))
# Full current state
fps = base + "/full_episode.wav"
dr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", 
                      "csv=p=0", fps], capture_output=True, text=True)
print("Current full_episode.wav:", dr.stdout.strip())
