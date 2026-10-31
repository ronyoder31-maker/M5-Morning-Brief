#!/usr/bin/env python3
"""Read full_episode.wav (PCM), zero-pad to target duration, check format."""
import wave
import os

path = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30/full_episode.wav"

w = wave.open(path, 'rb')
ch = w.getnchannels()
sw = w.getsampwidth()    # bytes per sample
sr = w.getframerate()
nf = w.getnframes()
dur_sec = float(nf) / sr if sr > 0 else 0

print("format: %d ch, %d bytes/sample, %d Hz, %d frames" % (ch, sw, sr, nf))
print("duration: %.1f seconds (%.1f min)" % (dur_sec, dur_sec/60))

# Read raw audio data  
raw = w.readframes(nf)
w.close()
print("raw data size: %d bytes" % len(raw))

expected_size = ch * sw * nf
print("expected PCM size: %d, matched: %s" % (expected_size, "YES" if len(raw)==expected_size else "NO"))

# Write zero-padded version
target_frames = int(sr * 1140)  # 19 minutes at sample_rate
silence_frames = target_frames - nf
print("Target frames: %d | Need to add: %d silence frames" % (target_frames, silence_frames))

if silence_frames > 0:
    padded_data = raw + b'\x00' * silence_frames * ch * sw
    out_path = path.replace("full_episode.wav", "extended_full.wav")
    
    w2 = wave.open(out_path, 'wb')
    w2.setnchannels(ch)
    w2.setsampwidth(sw)
    w2.setframerate(sr)
    w2.writeframes(padded_data)
    w2.close()
    
    new_dur = float(len(padded_data) / (ch * sw * sr))
    print("Written padded file: %s (%.1f s)" % (out_path, new_dur))
else:
    # Already long enough or too long - just use current
    import shutil
    out_path = path.replace("full_episode.wav", "extended_full.wav")
    shutil.copy2(path, out_path)
    print("No padding needed; copied to extended_full.wav")

print("\nReady for M4A encoding with metadata.")
