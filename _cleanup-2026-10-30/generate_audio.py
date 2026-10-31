#!/usr/bin/env python3
"""Generate TTS audio segments from M5 Morning Brief script using edge-tts."""
import subprocess, os, re, tempfile

script_path = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30/script.md"
output_dir = "/Users/casper/Podcasts/M5 Morning Brief/2026-10-30/wav_segs"
os.makedirs(output_dir, exist_ok=True)

with open(script_path) as f:
    lines = f.readlines()

# Parse dialogue segments (lines starting with "A:" or "B:")
segments = []
for line in lines:
    m = re.match(r'^([AB]): (.+)$', line.strip())
    if m:
        speaker = m.group(1)
        text = m.group(2)
        segments.append((speaker, text))

print(f"Found {len(segments)} dialogue segments")

# Voices: A=male (en-US-AndrewMultilingualNeural), B=female (en-US-AvaMultilingualNeural)
voices = {'A': 'en-US-AndrewMultilingualNeural', 'B': 'en-US-AvaMultilingualNeural'}

rate = '+5%'

success_count = 0
fail_count = 0
failed_segments = []

for i, (speaker, text) in enumerate(segments):
    voice = voices[speaker]
    outpath = os.path.join(output_dir, f"seg-{i:02d}.wav")
    
    # Write text to temp file to avoid shell quoting issues
    tmpf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    tmpf.write(text)
    tmpf.close()
    
    cmd = ['edge-tts', '-v', voice, '--rate', rate, '-f', tmpf.name, '--write-media', outpath]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    
    os.unlink(tmpf.name)
    
    if result.returncode == 0 and os.path.exists(outpath):
        size = os.path.getsize(outpath)
        success_count += 1
        print(f"Segment {i}: [OK] [{speaker}] {len(text)} chars -> {outpath} ({size} bytes)")
    else:
        fail_count += 1
        failed_segments.append(i)
        print(f"Segment {i}: [FAIL] [{speaker}] - {result.stderr[:300] if result.stderr else 'no output'}")

print(f"\nResult: {success_count} OK, {fail_count} failed out of {len(segments)} segments")
if failed_segments:
    print(f"Failed segments: {failed_segments}")

# List generated files
import glob
wav_files = sorted(glob.glob(os.path.join(output_dir, "*.wav")))
print(f"\nTotal WAV files: {len(wav_files)}")
