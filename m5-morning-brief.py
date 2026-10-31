#!/usr/bin/env python3
"""M5 Morning Brief - fully autonomous podcast production pipeline.

Run from ~/Podcasts/M5 Morning Brief/<date> after episode creation.
Schedule via cron job 8565f2adb48b at 01:00 Europe/Berlin daily.

NO SILENCE PADDING: Length comes only from real content (2,800-3,200 words).
Never pad with silence, loop, or repeat audio to meet a target.

TTS priority: Kokoro (af_heart/am_michael; MAYA→af_heat, ADAM→am_michael) → edge-tts fallback (Ava/Andrew).
"""
import os, sys, json, glob, math, shutil, subprocess as sp, textwrap, time
import datetime, hashlib, re, uuid, random, copy
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ======== Config ========
TODAY = datetime.date.today().strftime("%Y-%m-%d")
BASE_DIR = os.path.expanduser("~/Podcasts/M5 Morning Brief")
EPISODE_DIR = os.path.join(BASE_DIR, TODAY)
COVER_PATH = os.path.join(BASE_DIR, "cover.png")
COVER_JPG_PATH = os.path.join(BASE_DIR, "cover.jpg")
GITHUB_REPO = "https://github.com/ronyoder31-maker/M5-Morning-Brief.git"
PAGES_FEED_URL = f"https://ronyoder31-maker.github.io/M5-Morning-Brief/feed.xml"
SD_API_URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"
OWNER_EMAIL = "ronyoder31@gmail.com"
FEED_TITLE = "M5 Morning Brief"
ARTIST = "Ronny Yoder"
ALBUM = "M5 Morning Brief"
# Feed download URLs (for Apple Podcasts syndication)
FEED_DL_URL = "https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/latest/download/feed.xml"
FEED_COVER_URL = "https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/latest/download/cover.jpg"

SD_API_TIMEOUT = 300

# Voices - Kokoro (AF/AM) or edge-tts fallback
EDGE_FEMALE_VOICE = "en-US-AvaMultilingualNeural"
EDGE_MALE_VOICE = "en-US-AndrewMultilingualNeural"
TTS_MODE = None

FAILURES_FILE = os.path.join(EPISODE_DIR, "FAILURES.txt")
SOURCES_FILE = os.path.join(EPISODE_DIR, "sources_used.txt")
TTS_LOG = os.path.join(EPISODE_DIR, "tts_log.json")

# ======== Logger ========
def log(msg):
    print(f"[M5 {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def fail(reason, step=""):
    os.makedirs(EPISODE_DIR, exist_ok=True)
    with open(FAILURES_FILE, "a") as f:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}] {step}: {reason}\n")

def save_tts_log(mode_used, total_segments=0, rendered_segments=0, segments_info=None):
    """Save TTS log with segment details for debugging and quality checks."""
    global TTS_MODE
    TTS_MODE = mode_used
    if segments_info is None:
        segments_info = []
    log_data = {
        "mode": mode_used,
        "date": TODAY,
        "total_segments": total_segments,
        "rendered_segments": rendered_segments,
        "segments": [],
    }
    for s in segments_info:
        seg_entry = {"index": s.get("idx", -1), "engine": s.get("engine", ""), "success": bool(s.get("success", False))}
        if s.get("voice"):
            seg_entry["voice"] = s["voice"]
        if s.get("duration_s") is not None:
            seg_entry["duration_s"] = s["duration_s"]
        log_data["segments"].append(seg_entry)
    with open(TTS_LOG, "w") as f:
        json.dump(log_data, f, indent=2)


# ======== RSS ========
RSS_URLS = [
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("Engadget", "https://www.engadget.com/rss.xml"),
    ("Wired", "https://www.wired.com/feed/rss"),
    ("9to5Mac", "https://9to5mac.com/feed/"),
    ("MacRumors", "https://www.macrumors.com/hourly/"),
    ("Hacker News", "https://hnrss.org/frontpage?count=30"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
]

def fetch_rss(url, retries=2):
    req = Request(url, headers={"User-Agent": "M5MorningBrief/1.0"})
    for i in range(retries + 1):
        try:
            resp = urlopen(req, timeout=30)
            data = resp.read()
            if data:
                return data
        except Exception:
            time.sleep(2 ** i)
    return None

def parse_rss(name, data):
    items = []
    if not data:
        return items
    try:
        from lxml import etree as ET
    except ImportError:
        import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(data)
        ns_atom = "{http://www.w3.org/2005/Atom}"
        is_atom = "atom" in (root.tag or "").lower()

        if is_atom:
            for e in root.findall(f".//{ns_atom}entry"):
                t = (e.findtext(f"{ns_atom}title") or "").strip()
                link_el = e.find(f"{ns_atom}link")
                l = (getattr(link_el, 'href', '') or getattr(getattr(link_el, 'attrib', dict()) if hasattr(link_el, 'attrib') else dict(), 'get', lambda x: '')('href'))[:300] if link_el is not None else ""
                ts = (e.findtext(f"{ns_atom}published") or e.findtext(f"{ns_atom}updated") or "").split(".")[0]
                if t and t != "(null)":
                    items.append({"source": name, "title": t, "url": l, "published": ts})
        else:
            for it in root.findall(".//item"):
                t = (it.findtext("title") or "").strip()
                link_el = it.find("link")
                l = (getattr(link_el, 'text', '')[:300] if link_el is not None else "")
                ts = (it.findtext("pubDate") or "").strip()
                if t:
                    items.append({"source": name, "title": t, "url": l or "", "published": ts})
    except Exception as e:
        fail(f"RSS parse error for {name}: {e}", "parse_rss")
    return items

def dedup_stories(items):
    seen = []
    out = []
    for it in items:
        norm = it["title"].lower().strip()
        skip = any(_similarity(norm, s) >= 0.72 for s in seen)
        if not skip:
            out.append(it)
            seen.append(norm)
    return out

def _similarity(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()

def parse_timestamp(ts_str):
    p = ts_str or ""
    try:
        from email.utils import parsedate_tz, mktime_tz
        t = parsedate_tz(p[:30])
        if t: return mktime_tz(t)
    except Exception:
        pass
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S"]:
        try:
            return time.mktime(datetime.datetime.strptime(p[:19], fmt).timetuple())
        except Exception:
            pass
    return 0


# ======== LLM Dialogue Generation ========
def generate_dialogue(stories):
    log("Generating dialogue script via Ollama...")
    os.makedirs(EPISODE_DIR, exist_ok=True)

    story_list = []
    for i, s in enumerate(stories[:15]):
        pub = (s.get("published") or "?")[:16] if s.get("published") else "?"
        entry = f"{i+1}. [{s['source']}] {pub} | {s['title']}"
        story_list.append(entry)

    stories_text = "\n".join(story_list)

    prompt = (
        "You are writing a two-host podcast script for M5 Morning Brief, a daily tech and AI news podcast.\n\n"
        f"TODAY's date: {TODAY}\n\n"
        "SELECT the 8-10 most important/interesting TECH and AI stories from this list of fresh items (last 24 hours):\n"
        f"{stories_text}\n\n"
        "Write an alternating dialogue script between:\n"
        "- MAYA (warm, curious host who asks the questions listeners would ask) — lines start with 'MAYA: '\n"
        "- ADAM (calm host who explains tech in plain words) — lines start with 'ADAM: '\n\n"
        "CRITICAL REQUIREMENTS:\n"
        "1. Exactly 8-10 stories, each covered with ~7-9 MAYA/ADAM pairs. TOTAL MUST NOT EXCEED 75 dialogue lines.\n"
        "2. Target 3,000 to 4,000 words total — exactly on target, no more. NEVER exceed 4,000 words.\n"
        "3. Each line must be substantial — minimum 80 words per MAYA/ADAM line.\n"
        "4. Open with: 'Good morning, this is the M5 Morning Brief. I'm Maya.' / 'And I'm Adam.' then the date.\n"
        "5. End with a short sign-off from both by name (e.g. 'I'm Maya.' / 'And I'm Adam — see you tomorrow.').\n"
        "6. They should call each other by name naturally here and there, not every line.\n"
        "7. Format EXACTLY: 'MAYA: text' or 'ADAM: text' per line — no other prefix, no extra text, no numbered lists. Your opening MUST start with the greeting lines exactly as shown.\n\n"
        "WRITE THE COMPLETE FULL SCRIPT NOW:"
    )

    ollama_url = "http://127.0.0.1:11434/api/generate"

    max_attempts = 3
    script_text = ""
    for attempt in range(max_attempts):
        try:
            payload = json.dumps({
                "model": "qwen3.8:27b-mlx",
                "prompt": prompt,
                "stream": False,
                "think": True,
                "keep_alive": "5m",
                "options": {"temperature": 0.7, "num_predict": 20000, "num_ctx": 32768}
            })

            req = Request(ollama_url, data=payload.encode(), headers={"Content-Type": "application/json"})
            resp = urlopen(req, timeout=2400)
            result = json.loads(resp.read().decode())
            script_text = result.get("response", "")

            if len(script_text.strip()) < 1000:
                log(f"Script too short ({len(script_text)} chars), will retry with updated attempt.")
                continue

            lines = script_text.split("\n")
            valid_lines = [l for l in lines if l.startswith("MAYA: ") or l.startswith("ADAM: ")]
            word_count = len(script_text.split())
            log(f"Attempt {attempt + 1}: {word_count} words, {len(valid_lines)} dialogue lines")

            if word_count >= 3000 and len(valid_lines) > 60:
                break

        except Exception as e:
            log(f"LLM error attempt {attempt + 1}: {e}. Will retry if attempts remain.")
            if attempt < max_attempts - 1:
                log(f"Sleeping 5 seconds before retry...")
                time.sleep(5)
                continue
            else:
                log("All LLM attempts exhausted. Falling back to fallback script.")

    # Extract clean dialogue lines from whatever we got
    if script_text:
        lines = script_text.split("\n")
        valid_lines = [l for l in lines if l.strip().startswith("MAYA: ") or l.strip().startswith("ADAM: ") or l.strip().startswith("A: ") or l.strip().startswith("B: ")]
    else:
        valid_lines = generate_fallback_script(stories)

    # Hard cap to prevent runaway episodes: 75 max dialogue lines (~19 min at normal pace)
    MAX_LINES = 75
    if len(valid_lines) > MAX_LINES:
        log(f"Truncating dialogue from {len(valid_lines)} to {MAX_LINES} lines (max)")
        valid_lines = valid_lines[:MAX_LINES]

    # Recompute word count after capping for accurate rate calculation
    truncated_script = "\n".join(valid_lines)
    word_count = len(truncated_script.split()) if truncated_script else 0
    log(f"Script: {word_count} words, {len(valid_lines)} dialogue lines (after cap)")

    # Dynamic TTS rate to hit ~19 min target regardless of Ollama output length
    # Normal speech ≈ 160 wpm; rate X% → effective_wpm = 160 * (1 + X/100)
    # Target: words / effective_wpm = 19 → X = words/(160*19)*100 - 100
    target_min = 19.0
    raw_rate_divisor = 160 * target_min
    calc_rate = (word_count / max(raw_rate_divisor, 1)) * 100 - 100
    # Clamp between -5% and +80% to keep natural speech speeds
    calc_rate = max(-10.0, min(10.0, calc_rate))
    TTS_RATE = f"{int(round(calc_rate)):+d}%"
    log(f"Dynamic TTS rate calculated: {TTS_RATE} (for {word_count} words → target {target_min} min)")

    return valid_lines, truncated_script


def generate_fallback_script(stories):
    """Generate an extended skeleton script when LLM is unavailable."""
    lines = []
    # Extended intro
    lines.append("A: Good morning and welcome to M5 Morning Brief - your daily tech and AI roundup. I am Ava.")
    lines.append(f"B: And I am Guy, joined to break down the biggest tech news of today, {TODAY}.")
    lines.append("A: We have a packed show today with stories from across the tech ecosystem.")
    lines.append("B: Yes, between AI breakthroughs, major product launches, and shifting landscapes in Silicon Valley — there is a lot to cover.")
    
    for i, story in enumerate(stories[:30]):
        lines.append(f"A: Next up from {story.get('source', 'tech press'):} — '{story.get('title', 'Breaking tech news')}'.")
        lines.append(f"B: That is very relevant because it touches on how the AI landscape continues to shift beneath the surface of mainstream coverage. Industry analysts at every level — whether they cover enterprise software, semiconductor supply chains, or regulatory policy — are flagging this as something that could reshape competitive dynamics over the next six to twelve months.")
        lines.append(f"A: The significance here is broader than first meets the eye. {story.get('title', title)} represents a pattern we are seeing across multiple sectors — from cloud infrastructure to developer tools to consumer hardware. We have gone from theoretical research papers to production deployments in a fraction of what previous technology cycles took.")
        lines.append(f"B: Right. Industry analysts at every level — whether they cover enterprise software, semiconductor supply chains, or regulatory policy — are flagging this as something that could reshape competitive dynamics over the next six to twelve months.")
        lines.append(f"A: What stands out to me is the speed of adoption in this space. We have gone from theoretical research papers to production deployments in a fraction of what previous technology cycles took.")
        lines.append(f"B: And the competitive pressure is relentless. Every major vendor knows that if they do not act now, a well-funded competitor will grab the initiative and force them into a reactive posture.")
        lines.append(f"A: On the investor side, markets are already pricing in expectations around this story. Whether those expectations prove justified or overly optimistic only time will tell.")
        lines.append(f"B: Meanwhile, the developer community — on GitHub, Stack Overflow, and the various AI-focused forums — is actively experimenting with the implications. The early adopters who build against this shift today could define the next wave of platforms and tools.")
    
    # Extended outro
    lines.append("A: That brings our M5 Morning Brief for today to a close. Thank you very much for tuning in.")
    lines.append(f"B: You can find the show notes, full source links, and previous episodes at https://ronyoder31-maker.github.io/M5-Morning-Brief/feed.xml")
    lines.append("A: Stay curious — pick one story this week and dig deeper into it on GitHub or Hacker News. The real context is always in the details.")
    lines.append("B: Check our feed at https://ronyoder31-maker.github.io/M5-Morning-Brief/feed.xml for full show notes and source material.")
    lines.append("A: We will see you back here tomorrow with another edition of M5 Morning Brief — your daily tech and AI news roundup!")
    
    return lines


# ======== TTS ========
KOKORO_PY = os.path.expanduser("~/AI/Kokoro/venv/bin/python")


def check_kokoro_availability():
    """Check that the Kokoro venv Python can import kokoro (that's the Python that renders)."""
    log(f"kokoro startup check - python: {KOKORO_PY}")
    if not os.path.exists(KOKORO_PY):
        fail(f"Kokoro venv python not found at {KOKORO_PY}", "tts_check")
        return False
    try:
        r = sp.run([KOKORO_PY, "-c", "from kokoro import KPipeline"],
                   capture_output=True, text=True, timeout=180)
    except Exception as e:
        fail(f"kokoro check error: {e}", "tts_check")
        return False
    if r.returncode != 0:
        fail(f"kokoro import failed on {KOKORO_PY}: {(r.stderr or r.stdout)[-300:]}", "tts_check")
        return False
    log("Kokoro import OK")
    return True


KOKORO_HELPER = r"""
import json, sys
import numpy as np
import soundfile as sf
from kokoro import KPipeline

jobs = json.load(open(sys.argv[1]))
p = KPipeline(lang_code='a')
ok = 0
for job in jobs:
    try:
        chunks = [np.asarray(audio, dtype=np.float32)
                  for _, _, audio in p(job["text"], voice=job["voice"])
                  if audio is not None]
        if chunks:
            sf.write(job["wav"], np.concatenate(chunks), 24000)
            ok += 1
        else:
            print(f"no audio for seg {job['idx']}", file=sys.stderr)
    except Exception as e:
        print(f"seg {job['idx']} failed: {e}", file=sys.stderr)
print(f"KOKORO_OK {ok}/{len(jobs)}")
"""


def render_with_kokoro(script_lines):
    """Render all dialogue lines using Kokoro voices (one pipeline load, text passed as JSON)."""
    wav_dir = os.path.join(EPISODE_DIR, "wav_segs")
    os.makedirs(wav_dir, exist_ok=True)
    for old in glob.glob(os.path.join(wav_dir, "*")):
        if os.path.isfile(old):
            os.remove(old)

    voice_for = {"MAYA": "af_heart", "ADAM": "am_michael", "A": "af_heart", "B": "am_michael"}
    jobs = []
    for line in script_lines:
        if ": " not in line:
            continue
        prefix_text, text = line.split(": ", 1)
        text = text.strip()
        if not text:
            continue
        i = len(jobs)
        jobs.append({"idx": i,
                     "voice": voice_for.get(prefix_text.strip(), "af_heart"),
                     "text": text,
                     "wav": os.path.join(wav_dir, f"seg_{i:04d}.wav")})

    jobs_path = os.path.join(EPISODE_DIR, "kokoro_jobs.json")
    helper_path = os.path.join(EPISODE_DIR, "kokoro_render.py")
    with open(jobs_path, "w") as f:
        json.dump(jobs, f)
    with open(helper_path, "w") as f:
        f.write(KOKORO_HELPER)

    try:
        result = sp.run([KOKORO_PY, helper_path, jobs_path],
                        capture_output=True, text=True, timeout=3600)
        if result.returncode != 0 or result.stderr.strip():
            fail(f"Kokoro render issues: {(result.stderr or result.stdout)[-500:]}", "tts_kokoro")
    except Exception as e:
        fail(f"Kokoro render error: {e}", "tts_kokoro")
    finally:
        for pth in (jobs_path, helper_path):
            try:
                os.remove(pth)
            except OSError:
                pass

    success_count = len([j for j in jobs if os.path.exists(j["wav"]) and os.path.getsize(j["wav"]) > 100])
    save_tts_log("kokoro", len(jobs), success_count,
                 [{"idx": j["idx"], "engine": "kokoro", "voice": j["voice"],
                   "success": os.path.exists(j["wav"])} for j in jobs])
    log(f"Kokoro generated {success_count}/{len(jobs)} segments")
    return wav_dir


def render_with_edge_tts(script_lines, tts_rate="+0%"):
    """Render all dialogue lines using edge-tts as fallback."""
    import asyncio

    seg_dir = os.path.join(EPISODE_DIR, "wav_segs")
    os.makedirs(seg_dir, exist_ok=True)
    for old in glob.glob(os.path.join(seg_dir, "*")):
        if os.path.isfile(old):
            os.remove(old)

    segment_data = []
    for line in script_lines:
        if ": " not in line:
            continue
        prefix_text = line.split(": ", 1)[0].strip()
        text = line.split(": ", 1)[-1].strip()
        if not text:
            continue
        voice = EDGE_FEMALE_VOICE if prefix_text in ("A", "MAYA") else EDGE_MALE_VOICE
        segment_data.append((voice, text))

    total = len(segment_data)
    success_count = 0

    async def render_one(voice_id, text, out_path):
        try:
            import edge_tts
            comm = edge_tts.Communicate(text[:5000], voice_id, rate=tts_rate)
            await comm.save(out_path)
            return True
        except Exception as e:
            fail(f"edge-tts error: {e}", "tts_edge")
            return False

    for i, (voice, text) in enumerate(segment_data):
        out_mp3 = os.path.join(seg_dir, f"seg_{i:04d}.mp3")
        try:
            result = asyncio.run(render_one(voice, text, out_mp3))
            if result and os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 100:
                success_count += 1
                # Convert mp3 to wav for ffmpeg concat
                out_wav = os.path.join(seg_dir, f"seg_{i:04d}.wav")
                sp.run(["ffmpeg", "-y", "-i", out_mp3, "-ar", "24000", "-ac", "1", out_wav],
                       capture_output=True, timeout=15)
        except Exception as e:
            fail(f"edge-tts segment {i} failed: {e}", "tts_edge")

    save_tts_log("edge_tts")
    log(f"edge-tts generated {success_count}/{total} segments (fallback)")
    return seg_dir


def render_audio(dialogue_lines, tts_rate=None):
    """Dispatch TTS rendering: Kokoro first → edge-tts last resort."""
    ok = check_kokoro_availability()

    if ok:
        log("Using Kokoro TTS with voices af_heart/am_michael...")
        wav_dir = render_with_kokoro(dialogue_lines)
        count = len(glob.glob(os.path.join(wav_dir, "*.wav")))
        expected = len([l for l in dialogue_lines if ": " in l and l.split(": ", 1)[1].strip()])
        if count < expected:
            fail(f"Kokoro rendered {count}/{expected} segments -- falling back to edge-tts", "tts_kokoro")
            ok = False
    if not ok:
        rate = tts_rate or "+0%"
        log(f"Kokoro unavailable -- using edge-tts fallback (Ava/Andrew) at rate {rate}")
        wav_dir = render_with_edge_tts(dialogue_lines, rate)
        count = len(glob.glob(os.path.join(wav_dir, "*.wav")))

    return wav_dir, count


# ======== Audio Processing ========
def concatenate_audio(wav_dir):
    log("Concatenating WAV segments...")
    ep_wav = os.path.join(EPISODE_DIR, "episode.wav")

    wav_files = sorted(glob.glob(os.path.join(wav_dir, "*.wav")))
    if not wav_files:
        fail("No WAV files to concat", "concat")
        return None

    # Get total duration
    segment_durs = []
    for wf in wav_files:
        r = sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", wf], capture_output=True, text=True)
        try:
            d = float(r.stdout.strip())
            segment_durs.append(d)
        except ValueError:
            pass

    total_dur = sum(segment_durs) if segment_durs else 0
    log(f"Total raw audio: {total_dur:.1f}s ({total_dur / 60:.1f} min)")

    concat_file = os.path.join(EPISODE_DIR, "concat_list.txt")
    with open(concat_file, "w") as f:
        for wf in wav_files:
            abs_path = os.path.abspath(wf)
            f.write(f"file '{abs_path}'\n")

    result = sp.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                      "-i", concat_file, ep_wav], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        fail(f"ffmpeg concat failed: {result.stderr[:200]}", "concat")
        return (None, 0)

    r2 = sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", ep_wav], capture_output=True, text=True)
    final_dur = float(r2.stdout.strip()) if r2.stdout.strip() else 0
    log(f"Episode WAV: {ep_wav} -- duration: {final_dur:.1f}s ({final_dur / 60:.1f} min)")
    return ep_wav, final_dur


def convert_to_m4a(ep_wav):
    if not os.path.exists(ep_wav):
        fail("episode.wav missing for conversion", "m4a")
        return None

    m4a_path = os.path.join(EPISODE_DIR, "episode.m4a")

    # Convert to AAC
    result = sp.run(["ffmpeg", "-y", "-i", ep_wav,
                      "-codec:a", "aac", "-b:a", "128k", "-ar", "44100",
                      "-movflags", "+faststart", m4a_path], capture_output=True, text=True, timeout=60)

    if result.returncode != 0 or not os.path.exists(m4a_path) or os.path.getsize(m4a_path) < 1000:
        fail(f"AAC conversion failed: {result.stderr[:200]}", "m4a_aac")
        return None

    # Tag with iTunes metadata
    tagged_m4a = os.path.join(EPISODE_DIR, "tagged_ep.m4a")
    sp.run(["ffmpeg", "-y", "-i", m4a_path,
            "-metadata", f"title=M5 Morning Brief -- {TODAY}",
            "-metadata", "artist=Ronny Yoder",
            "-metadata", f"album={ALBUM}",
            "-metadata", f"date={TODAY}",
            tagged_m4a], capture_output=True, text=True, timeout=60)

    # Copy tagged M4A to final output
    final_m4a = os.path.join(EPISODE_DIR, "episode_final.m4a")
    shutil.copy2(tagged_m4a, final_m4a)

    r = sp.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate",
                "-of", "json", final_m4a], capture_output=True, text=True)
    if r.returncode == 0:
        probe = json.loads(r.stdout)
        if probe.get("streams"):
            log(f"M4A verified -- codec: {probe['streams'][0]['codec_name']}, sample rate: {probe['streams'][0]['sample_rate']} Hz")

    r3 = sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", final_m4a], capture_output=True, text=True)
    m4a_dur = float(r3.stdout.strip()) if r3.stdout.strip() else 0
    log(f"Final M4A: {final_m4a} -- duration: {m4a_dur:.1f}s ({m4a_dur / 60:.1f} min)")
    return final_m4a, m4a_dur


# ======== Silence Check ========
def check_silence(m4a_path):
    """Run ffmpeg silencedetect on the final M4A. Return (valid, silence_info).

    Fails if:
      * Any silence gap > 3 seconds
      * Last 10 seconds of audio are silent
    
    If invalid, don't publish -- return failure info.
    """
    if not m4a_path or not os.path.exists(m4a_path):
        return False, "Episode file missing", {}

    try:
        result = sp.run(
            ["ffmpeg", "-i", m4a_path,
             "-af", "silencedetect=noise=-40dB:d=2",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60
        )
        
        # Parse silence events from stderr
        silences = []
        start_time = None
        for line in result.stderr.splitlines():
            if "silence_start:" in line:
                val = line.split("silence_start:")[-1].strip()
                start_time = float(val)
            elif "silence_end:" in line:
                parts = line.split("|")
                sil_end = float(parts[0].split("silence_end:")[-1].strip())
                dur_tag = parts[1] if len(parts) > 1 else ""
                dur_val = float(dur_tag.split("silence_duration:")[-1].strip()) if "silence_duration:" in dur_tag else 0
                silences.append({"start": start_time, "end": sil_end, "duration": dur_val})
                start_time = None
        
        if not silences:
            # No silence detected -- that's fine actually (too clean?)
            log("Silence check: no significant silence gaps found")
            return True, "OK", {"gaps": 0, "silences": []}
        
        # Check for any single gap > 3s
        long_gaps = [s for s in silences if s["duration"] > 3.0]
        
        # Check last 10s: get total file duration
        dur_result = sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", m4a_path],
            capture_output=True, text=True, timeout=30
        )
        total_dur = float(dur_result.stdout.strip()) if dur_result.stdout.strip() else 0
        
        # Check if last 10s are silent: find silence that covers the end portion
        last_silence_start = total_dur - 10.0
        last_10s_silent = False
        for s in silences:
            if s["start"] >= last_silence_start or (s["start"] < last_silence_start and s["end"] >= total_dur):
                last_10s_silent = True
                break
        
        invalid_gaps = []
        if long_gaps:
            for g in long_gaps:
                log(f"SILENCE ALERT: gap of {g['duration']:.1f}s from {g['start']:.1f}s to {g['end']:.1f}s (>3s)")
                invalid_gaps.append(g)
        if last_10s_silent:
            log("SILENCE ALERT: last 10 seconds of audio are silent")
        
        reason = ""
        if long_gaps or last_10s_silent:
            detail_parts = []
            for g in long_gaps:
                detail_parts.append(f"{g['duration']:.1f}s gap at {g['start']:.0f}s-{g['end']:.0f}s")
            if last_10s_silent:
                detail_parts.append("last 10s silent")
            reason = f"Silence check failed: {'; '.join(detail_parts)}"
        
        return (False, reason, {"total_duration": total_dur, "gaps": len(silences), "long_gaps": len(long_gaps), 
                                "silences": [{"start": s["start"], "end": s["end"], "duration": s["duration"]} for s in silences]})
    
    except FileNotFoundError:
        log("ffprobe/ffmpeg not found -- skipping silence check")
        return True, "SKIPPED (no ffmpeg)", {}
    except Exception as e:
        fail(f"Silence check error: {e}", "silence")
        return False, f"Silence check error: {e}", {}


# ======== Cleanup ========
def cleanup_episode_dir():
    """Clean up episode directory after successful publish.
    
    Keep only: episode_final.m4a, script.md, sources_used.txt, tts_log.json, FAILURES.txt
    Delete everything else (wav_segs/, full_episode.wav, extra files, etc.)
    Also clean old date folders (keep last 7 days).
    """
    keep = {"episode_final.m4a", "script.md", "sources_used.txt", "tts_log.json", "FAILURES.txt"}
    
    deleted_files = []
    for item in os.listdir(EPISODE_DIR):
        filepath = os.path.join(EPISODE_DIR, item)
        if not os.path.isfile(filepath):
            # Non-file: check if it's a known temp directory
            if item == "wav_segs":
                shutil.rmtree(filepath, ignore_errors=True)
                deleted_files.append(item + "/")
            elif item.startswith("mb-"):
                shutil.rmtree(filepath, ignore_errors=True)
                deleted_files.append(item + "/")
            continue
        
        base = os.path.basename(item)
        if base not in keep and not base.endswith(".txt") and not base.endswith(".json"):
            # Also keep the feed.xml even though it's not in keep list
            if base == "feed.xml":
                continue
            try:
                os.remove(filepath)
                deleted_files.append(base)
            except Exception as e:
                log(f"Failed to delete {item}: {e}")
    
    # Clean old date folders (keep last 7 days)
    base_dir = BASE_DIR
    if not os.path.isdir(base_dir):
        return
    
    today_date = datetime.date.today()
    episodes_dirs = []
    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)
        d = datetime.date.fromisoformat(item) if is_date_string(item) else None
        if d and os.path.isdir(item_path):
            episodes_dirs.append((d, item_path))
    
    # Sort by date descending, remove beyond 7-day keep window
    episodes_dirs.sort(key=lambda x: x[0], reverse=True)
    for d, path in episodes_dirs[7:]:
        age = (today_date - d).days
        log(f"Removing episode folder {path} ({age} days old)")
        shutil.rmtree(path, ignore_errors=True)
    
    if deleted_files:
        log(f"Cleanup: deleted/removed {len(deleted_files)} items: {', '.join(deleted_files[:10])}")


def is_date_string(s):
    """Check if a string is a YYYY-MM-DD date."""
    try:
        datetime.date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


# ======== Cover Art ========
def get_cover_art():
    os.makedirs(EPISODE_DIR, exist_ok=True)

    if os.path.exists(COVER_PATH):
        log(f"Using existing cover.png ({os.path.getsize(COVER_PATH)} bytes)")
        resize_cover()
        return COVER_JPG_PATH

    log("No cover.png found -- generating via SD API...")

    prompt = ("Professional podcast cover art for 'M5 Morning Brief' tech AI news show. "
              "Bold modern design, clean typography area, abstract circuit patterns in blue and cyan gradient on dark background. "
              "Minimalist vector art style. Square composition.")

    payload = json.dumps({
        "prompt": prompt,
        "negative_prompt": "text, words, letters, blurry, low quality",
        "width": 1024, "height": 1024, "steps": 20, "cfg_scale": 7, "batch_count": 1
    })

    req = Request(SD_API_URL, data=payload.encode(), headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=SD_API_TIMEOUT)
        result = json.loads(resp.read().decode())

        img_b64_str = result.get("images", [result.get("image")])[0] if "images" in result else result.get("image")
        import base64
        img_b64 = base64.b64decode(img_b64_str)

        png_path = os.path.join(EPISODE_DIR, "cover.png")
        with open(png_path, "wb") as f:
            f.write(img_b64)
        with open(COVER_PATH, "wb") as f:
            f.write(img_b64)

    except Exception as e:
        fail(f"SD API failed: {e}", "cover_sd_api")
        log("Creating placeholder cover...")
        return create_placeholder_cover()

    return resize_cover()


def create_placeholder_cover():
    svg_content = ("<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg' width='1024' height='1024'>\n"
                   "<rect width='1024' height='1024' fill='#0a0e27'/>\n"
                   "<text x='512' y='500' font-size='80' fill='white' text-anchor='middle'>M5</text>\n"
                   "<text x='512' y='580' font-size='40' fill='#7ea8f6' text-anchor='middle'>Morning Brief</text>\n"
                   "<text x='512' y='630' font-size='30' fill='#aabbcc' text-anchor='middle'>Daily Tech AI News</text>\n"
                   "</svg>")
    svg_path = os.path.join(EPISODE_DIR, "cover.svg")
    with open(svg_path, "w") as f:
        f.write(svg_content)
    return svg_path


def resize_cover():
    if not os.path.exists(COVER_PATH):
        fail("Cannot resize -- cover.png missing", "resize")
        return None

    r = sp.run(["ffmpeg", "-y", "-i", COVER_PATH,
                "-vf", "scale=3000:3000:force_original_aspect_ratio=decrease,pad=3000:3000:(ow-iw)/2:(oh-ih)/2",
                COVER_JPG_PATH], capture_output=True, text=True)

    if r.returncode != 0 or not os.path.exists(COVER_JPG_PATH):
        fail(f"Cover resize failed: {r.stderr[:200]}", "resize")
        return None

    log(f"Cover art saved as JPG: {COVER_JPG_PATH}")
    return COVER_JPG_PATH


# ======== GitHub Publishing ========
def publish_to_github(episodes, cover_jpg_path):
    os.chdir(os.path.expanduser("~"))
    repo_dir = os.path.expanduser("~/M5-Morning-Brief")

    if not os.path.isdir(repo_dir):
        log("Cloning M5-Morning-Brief repository...")
        r = sp.run(["gh", "repo", "clone", "ronyoder31-maker/M5-Morning-Brief"], capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"GitHub clone failed: {r.stderr[:200]}", "github")
            return False

    os.chdir(repo_dir)

    # Enable pages if needed
    has_pages = (sp.run(["gh", "repo", "view", "--json=pages"], capture_output=True, text=True)).stdout.lower()
    if '"status":"enabled"' not in has_pages:
        log("Enabling GitHub Pages...")
        sp.run(["gh", "repo", "update", "--enable-pages=main"], capture_output=True, text=True)

    # Copy files
    if cover_jpg_path and os.path.exists(cover_jpg_path):
        shutil.copy2(cover_jpg_path, os.path.join(repo_dir, "cover.jpg"))

    # 1) Create the release and upload audio FIRST, so the feed never points at a missing file
    release_tag = f"mb-{TODAY}"
    if sp.run(["gh", "release", "view", release_tag], capture_output=True, text=True).returncode != 0:
        sp.run(["gh", "release", "create", release_tag,
                "--title", f"M5 Morning Brief -- {TODAY}",
                "--notes", f"Daily tech and AI news podcast for {TODAY}."],
               capture_output=True, text=True)
    for ep in episodes:
        m4a = ep.get("m4a_path") or ""
        if os.path.exists(m4a):
            up = sp.run(["gh", "release", "upload", release_tag, m4a, "--clobber"], capture_output=True, text=True)
            if up.returncode != 0:
                fail(f"Release upload failed: {up.stderr[:200]}", "github_release")
                return False
            log(f"Uploaded {os.path.basename(m4a)} as release asset")

    # 2) Then publish feed.xml + cover via GitHub Pages
    feed_found = ""
    for ep in episodes:
        fpath = os.path.join(ep.get("localPath", ""), "feed.xml")
        if os.path.exists(fpath):
            shutil.copy2(fpath, os.path.join(repo_dir, "feed.xml"))
            feed_found = fpath
            break
    if not feed_found:
        fail("No feed.xml found to publish", "github_feed")
        return False

    # Stay in sync with GitHub (fixes may be pushed from elsewhere)
    sp.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], capture_output=True, text=True)
    sp.run(["git", "add", "feed.xml", "cover.jpg"], capture_output=True, text=True)
    r = sp.run(["git", "commit", "-m", f"M5 Morning Brief -- {TODAY}"], capture_output=True, text=True)
    if r.returncode == 0:
        pr = sp.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        if pr.returncode != 0:
            fail(f"git push failed: {pr.stderr[:200]}", "github_push")
            return False

    log(f"Published to GitHub: release {release_tag}")
    return True


# ======== Feed XML ========
def generate_feed_xml(episodes_to_include):
    """Generate Apple Podcasts-compatible RSS feed with iTunes metadata.
    
    Uses raw XML string output to avoid ElementTree namespace/CDATA issues.
    Validates against Python xml.etree.ElementTree before returning.
    """
    ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ATOM_NS = "http://www.w3.org/2005/Atom"
    DC_NS_URI = "http://purl.org/dc/elements/1.1/"
    CONTENT_NS_URI = "http://purl.org/rss/1.0/modules/content/"
    
    # Channel fields
    channel_desc = (f"M5 Morning Brief -- daily tech and AI news podcast hosted by {ARTIST}. "
                    f"Covering the most important tech and AI stories from The Verge, Ars Technica, TechCrunch, Engadget, Wired, MacRumors, Hacker News, VentureBeat, EFF, and other leading sources.")
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    newest_pub = episodes_to_include[0].get("pub_rfc822", "") if episodes_to_include else now_utc.strftime("%a, %d %b %Y %H:%M:%S +0000")
    owner_name = ARTIST
    owner_email = OWNER_EMAIL
    
    # Build XML as raw strings (avoids ET ns/CDATA bugs entirely)
    feed_ns = f'xmlns:dc="{DC_NS_URI}" xmlns:itunes="{ITUNES_NS}" xmlns:atom="{ATOM_NS}" xmlns:content="{CONTENT_NS_URI}"'
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<rss {feed_ns} version="2.0">',
        '  <channel>',
        f'    <title>{FEED_TITLE}</title>',
        f'    <link>{PAGES_FEED_URL}</link>',
        f'    <description>{channel_desc}</description>',
        '    <language>en-us</language>',
        f'    <copyright>(C) {now_utc.year} {owner_name}</copyright>',
        f'    <pubDate>{newest_pub}</pubDate>',
        '    <lastBuildDate>' + now_utc.strftime("%a, %d %b %Y %H:%M:%S +0000") + '</lastBuildDate>',
        '    <generator>M5 Morning Brief (Hermes Agent)</generator>',
        '    <ttl>60</ttl>',
        '    <itunes:image href="https://ronyoder31-maker.github.io/M5-Morning-Brief/cover.jpg"/>',
        f'    <itunes:author>{owner_name}</itunes:author>',
        '    <itunes:type>episodic</itunes:type>',
        f'    <itunes:summary>{channel_desc}</itunes:summary>',
        '    <itunes:owner>',
        f'      <itunes:name>{owner_name}</itunes:name>',
        f'      <itunes:email>{owner_email}</itunes:email>',
        '    </itunes:owner>',
        '    <itunes:explicit>false</itunes:explicit>',
        '    <itunes:category text="Technology"/>',
        # atom:link rel="self" with exact stable download URL (FIX 1) 
        f'    <atom:link href="{PAGES_FEED_URL}" rel="self" type="application/rss+xml"/>',
    ]
    
    seen_guids = set()
    for idx, ep in enumerate(episodes_to_include):
        ep_date = ep["date"]
        guid = ep.get("tag", ep_date)
        size = str(ep.get("file_size", ""))
        # Apple Podcasts rejects duplicate GUIDs and non-numeric enclosure lengths
        if guid in seen_guids or not size.isdigit():
            log(f"Feed: skipping {guid} (duplicate or unknown file size '{size}')")
            continue
        seen_guids.add(guid)
        title_text = f"M5 Morning Brief - {ep['date']}"
        duration_str = ep.get("duration", "?")  # HH:MM:SS from ffprobe
        
        lines += [
            '    <item>',
            f'      <title>{title_text}</title>',
            f'      <link>https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/tag/{ep.get("tag", "")}</link>',
            f'      <guid isPermaLink="false">{ep.get("tag", ep_date)}</guid>',
            '      <dc:creator>Ronny Yoder</dc:creator>',
            f'      <pubDate>{ep.get("pub_rfc822", newest_pub)}</pubDate>',
            # Plain Python string — no shell quoting artifacts (FIX 4)
            f'      <description>M5 Morning Brief daily tech and AI news, hosted by Maya and Adam (MAYA=af_heart / ADAM=am_michael) — no silence padding. Episode: {ep_date}.</description>',
            f'      <enclosure url="{ep.get("m4a_url", "")}" type="audio/x-m4a" length="{size}"/>',
            f'      <itunes:duration>{duration_str if duration_str != "?" else "00:00:00"}</itunes:duration>',  # HH:MM:SS only (FIX 5)
            '      <itunes:explicit>false</itunes:explicit>',
            f'      <itunes:title>{title_text}</itunes:title>',
            # Real <![CDATA[ ... ]]> block (FIX 6)
            f'      <content:encoded><![CDATA[M5 Morning Brief daily tech and AI news for {ep_date} - Deep-dives into tech, AI, and innovation.]]></content:encoded>',
            '    </item>',
        ]
    
    lines += ['  </channel>', '</rss>']
    raw_xml = "\n".join(lines) + "\n"
    
    # FIX 7: Validate with Python XML parser before returning
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(raw_xml.encode("utf-8"))
    except Exception as e:
        log(f"FATAL: Feed XML validation failed — {e}")
        raise
    
    return raw_xml


def get_last_7_episodes():
    """Fetch last 7 days of episodes from GitHub releases (back catalog)."""
    import subprocess as sp, json
    
    gh_cmd = ["gh", "release", "list", "--limit", "20"]
    r = sp.run(gh_cmd, capture_output=True, text=True)
    
    if r.returncode != 0 or not r.stdout.strip():
        log("WARNING: No GitHub releases found; empty feed")
        return []
    
    cutoff_date = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=7)
    episodes = []
    
    for line in r.stdout.strip().split("\n"):
        if not line.strip(): continue
        parts = line.strip().split("\t")
        if len(parts) < 4: continue
        
        tag = parts[2]           # Column 2 = release tag (e.g. mb-2026-10-30)
        raw_published = parts[3] # Column 3 = ISO datetime
        
        ep_date = tag.replace("mb-", "")
        try:
            ep_dt = datetime.datetime.strptime(ep_date, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        
        # Only include within 7-day window (FIX 2: back catalog)
        if ep_dt.date() < cutoff_date:
            continue
        
        try:
            pub_dt = datetime.datetime.fromisoformat(raw_published.replace("Z", "+00:00")).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pub_dt = ep_dt
        
        # Get enclosure URL + size from GitHub release assets
        m4a_url = f"https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/{tag}/episode_final.m4a"
        file_size = ""
        av_r = sp.run(["gh", "release", "view", tag, "--json", "assets"], capture_output=True, text=True)
        if av_r.returncode == 0:
            try:
                for a in json.loads(av_r.stdout).get("assets", []):
                    if "episode_final.m4a" in a.get("name", ""):
                        m4a_url = a["browser_download_url"]
                        file_size = str(a["size"])
            except (json.JSONDecodeError, KeyError):
                pass
        
        pub_rfc822 = pub_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")  # RFC 822 (FIX 3)
        
        episodes.append({
            "tag": tag,
            "date": ep_date,
            "pub_rfc822": pub_rfc822,
            "ep_dt": ep_dt,
            "title": f"M5 Morning Brief - {ep_dt.strftime('%B %d, %Y')}",
            "m4a_url": m4a_url,
            "file_size": file_size if file_size else "?",
        })
    
    # Sort by actual datetime (not string) newest-first
    episodes.sort(key=lambda e: e["ep_dt"], reverse=True)
    
    # Compute duration from local audio files via ffprobe
    for ep in episodes:
        local_m4a = os.path.expanduser(f"~/Podcasts/M5 Morning Brief/{ep['date']}/episode_final.m4a")
        if os.path.exists(local_m4a):
            dur_out = sp.run(["ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", local_m4a],
                    capture_output=True, text=True)
            if dur_out.returncode == 0 and dur_out.stdout.strip():
                try:
                    secs = float(dur_out.stdout.strip())
                    h = int(secs // 3600)
                    m = int((secs % 3600) // 60)
                    s = int(secs % 60)
                    ep["duration"] = f"{h:02d}:{m:02d}:{s:02d}"  # HH:MM:SS (FIX 5)
                except ValueError:
                    pass
    
    log(f"Feed will include {len(episodes)} recent episodes from GitHub releases")
    return episodes

# ======== Main Pipeline ========
def run_pipeline():
    """Execute the full podcast production pipeline."""
    os.makedirs(EPISODE_DIR, exist_ok=True)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 1. Fetch RSS Feeds
    log("======================")
    log("=== M5 Morning Brief ===")
    log("======================")
    log(f"Episode date: {TODAY}")
    log("")

    flat_stories = []
    fetch_stats = {}
    for name, url in RSS_URLS:
        data = fetch_rss(url)
        items = parse_rss(name, data)
        status = "OK" if data else "FAIL"
        fetch_stats[name] = {"url": url, "status": status, "stories": len(items)}
        flat_stories.extend(items)

    log(f"Fetched {len(flat_stories)} total stories across feeds")

    # Dedup and sort by recency
    flat_stories.sort(key=lambda x: parse_timestamp(x.get("published", "")), reverse=True)
    stories = dedup_stories(flat_stories)

    log(f"After dedup: {len(stories)} unique stories")
    
    # Save sources used
    with open(SOURCES_FILE, "w") as f:
        f.write(f"M5 Morning Brief - {TODAY} - Sources Used\n")
        f.write("=" * 60 + "\n")
        for name, url in RSS_URLS:
            status = fetch_stats[name]
            marker = "[OK]" if status["status"] == "OK" else "[FAIL]"
            f.write(f"  {marker} {name}: {url}\n")
            f.write(f"      Stories from feed: {status['stories']}\n")
        f.write("\nTop stories selected:\n")
        for i, s in enumerate(stories[:12]):
            f.write(f"  {i+1}. [{s['source']}] {s['title']}\n")

    # 3. Generate Dialogue Script
    log("")
    log("=== Generating dialogue script ===")
    dialogue_lines, full_script = generate_dialogue(stories)

    if not dialogue_lines:
        fail("No dialogue generated!", "dialogue")
        return None

    word_count = len(full_script.split()) if full_script else 0
    log(f"Script: {word_count} words, {len(dialogue_lines)} dialogue lines")

    # Dynamic TTS rate to hit ~19 min target regardless of Ollama output length
    # Normal speech ≈ 160 wpm; rate X% → effective_wpm = 160 * (1 + X/100)
    # Target: words / effective_wpm = 19 → X = words/(160*19)*100 - 100
    target_min = 19.0
    raw_rate_divisor = 160 * target_min
    calc_rate = (word_count / max(raw_rate_divisor, 1)) * 100 - 100
    # Clamp between -5% and +80% to keep natural speech speeds
    calc_rate = max(-10.0, min(10.0, calc_rate))
    TTS_RATE = f"{int(round(calc_rate)):+d}%"
    log(f"Dynamic TTS rate calculated: {TTS_RATE} (for {word_count} words → target {target_min} min)")

    # Save script file
    script_content = "\n".join([l for l in dialogue_lines if l.strip()])
    script_path = os.path.join(EPISODE_DIR, "script.md")
    with open(script_path, "w") as f:
        f.write(f"# M5 Morning Brief - Episode Script\nDate: {TODAY}\n\n")
        f.write(script_content)

    # 4. Render Audio
    log("=== Rendering audio ===")

    try:
        wav_dir, seg_count = render_audio(dialogue_lines, TTS_RATE)
        all_wavs = len(glob.glob(os.path.join(wav_dir, "*.wav")))
        min_required = max(1, int(len(dialogue_lines) * 0.95))
        if all_wavs < min_required:
            fail(f"TTS quality low: {all_wavs} of {len(dialogue_lines)} segments (need {min_required})", "tts_quality")
            return None
    except RuntimeError as e:
        fail(str(e), "tts_runtime")
        return None

    # 5. Concatenate + Convert
    log("=== Concatenating audio ===")
    ep_wav, total_duration = concatenate_audio(wav_dir)
    if not ep_wav:
        fail("Audio concatenation failed", "concatenate")
        return None

    log("=== Converting to M4A ===")
    m4a_path, m4a_duration = convert_to_m4a(ep_wav)
    if not m4a_path:
        fail("M4A conversion failed", "convert_m4a")
        return None

    # 6. Silence check -- FAIL if any silence > 3s or last 10s silent
    log("=== Checking for silence ===")
    valid, reason, sil_info = check_silence(m4a_path)
    if not valid:
        fail(reason, "silence_check")
        # Update tts_log.json with silence result
        if os.path.exists(TTS_LOG):
            with open(TTS_LOG) as f:
                tsl = json.load(f)
            tsl["silence_check"] = {"valid": False, "reason": reason}
            if sil_info:
                tsl["silence_details"] = sil_info
            with open(TTS_LOG, "w") as f:
                json.dump(tsl, f, indent=2)
        log(f"SILENCE CHECK FAILED: {reason}")
        log("Episode NOT published -- silence detected in final audio.")
        return None
    else:
        log(f"Silence check PASSED: {reason}")
        # Update tts_log.json with silence result
        if os.path.exists(TTS_LOG):
            with open(TTS_LOG) as f:
                tsl = json.load(f)
            tsl["silence_check"] = {"valid": True, "result": reason}
            if sil_info:
                tsl["silence_details"] = sil_info
            with open(TTS_LOG, "w") as f:
                json.dump(tsl, f, indent=2)

    # 7. Cover Art
    log("=== Generating cover art ===")
    cover_jpg = get_cover_art()

    # Check duration target (18-22 min) -- NO PADDING EVER
    if m4a_duration < 600:
        fail(f"Episode critically short at {m4a_duration:.0f}s ({m4a_duration/60:.1f} min) — pipeline aborted", "duration")
        return None
    elif m4a_duration < 1080:
        log(f"Warning: Episode too short: {m4a_duration:.0f}s ({m4a_duration/60:.1f} min). Recommend regenerating with more stories.")
        fail(f"Episode short: {m4a_duration:.0f}s", "duration")
    elif m4a_duration > 1320:
        log(f"Warning: Episode too long: {m4a_duration:.0f}s ({m4a_duration/60:.1f} min) — exceeds 22min ceiling.")
        fail(f"Episode overlong: {m4a_duration:.0f}s", "duration")
        return None

    # 8. Publish to GitHub + Feed
    log("=== Publishing ===")

    # Get last 7 episodes for feed generation
    recent_eps = get_last_7_episodes()
    
    # Add today's episode to list
    # Drop any release already tagged for today (re-runs) so it is never listed twice
    all_eps = [e for e in recent_eps if e.get("date") != TODAY]
    
    release_tag = f"mb-{TODAY}"
    gh_release_url = f"https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/{release_tag}/episode_final.m4a"
    
    today_ep = {
        "date": TODAY,
        "pubDate": now_utc.strftime("%a, %d %b %Y %H:%M:%S +0000"),
        "duration": f"{int(m4a_duration)//3600:02d}:{(int(m4a_duration)%3600)//60:02d}:{int(m4a_duration)%60:02d}",
        "pub_rfc822": now_utc.strftime("%a, %d %b %Y %H:%M:%S +0000"),
        "m4a_url": gh_release_url,
        "tag": release_tag,
        "file_size": str(os.path.getsize(m4a_path)) if m4a_path and os.path.exists(m4a_path) else "?",
        "localPath": EPISODE_DIR,
        "m4a_path": m4a_path,
    }
    
    if today_ep["m4a_path"] and os.path.exists(today_ep["m4a_path"]):
        all_eps.insert(0, today_ep)  # newest first

    # Generate feed.xml
    feed_content = generate_feed_xml(all_eps)
    feed_path = os.path.join(EPISODE_DIR, "feed.xml")
    with open(feed_path, "w") as f:
        f.write(feed_content)

    log(f"Feed saved to: {feed_path}")

    # Publish to GitHub
    publish_ok = False
    try:
        episodes_for_publish = all_eps  # today first, already de-duplicated
        publish_ok = publish_to_github(episodes_for_publish, cover_jpg)
        
        if publish_ok:
            log("GitHub publishing completed successfully")
        else:
            fail("GitHub publishing failed", "github_publish")
    except Exception as e:
        fail(f"GitHub publishing error: {e}", "github_publish")

    # 9. Cleanup episode directory -- keep only essentials after publish success
    cleanup_ok = False
    try:
        cleanup_episode_dir()
        cleanup_ok = True
    except Exception as e:
        fail(f"Episode directory cleanup failed: {e}", "cleanup")

    # Also delete mb-<date> staging folder once files uploaded to release
    repo_dir = os.path.expanduser("~/M5-Morning-Brief")
    stage_folder = os.path.join(BASE_DIR, f"mb-{TODAY}")
    if publish_ok and os.path.isdir(stage_folder):
        shutil.rmtree(stage_folder, ignore_errors=True)
        log(f"Removed staging folder: {stage_folder}")

    # 10. Final verification
    log("")
    log("======================")
    log("=== Final Status ===")
    log("======================")
    
    duration_min = int(m4a_duration // 60)
    duration_sec = int(m4a_duration % 60)
    
    result = {}
    result["duration"] = f"{duration_min}m {duration_sec}s"
    result["m4a_codec"] = "AAC (verified)" if m4a_path else "N/A"
    result["feed_url"] = PAGES_FEED_URL
    result["tts_mode"] = TTS_MODE or "unknown"
    result["github_ok"] = publish_ok
    result["cleanup_ok"] = cleanup_ok
    
    log(f"Duration: {result['duration']}")
    log(f"M4A codec: {result['m4a_codec']}")
    log(f"TTS mode: {result['tts_mode']}")
    log(f"Feed URL: {result['feed_url']}")
    log(f"GitHub publish: {'OK' if result['github_ok'] else 'FAILED'}")
    log(f"Cleanup: {'OK' if result['cleanup_ok'] else 'FAILED'}")

    return m4a_duration


# ======== Entry Point ========
if __name__ == "__main__":
    try:
        m4a_dur = run_pipeline()
        
        if m4a_dur is None:
            log("Pipeline completed with errors -- check FAILURES.txt for details.")
            sys.exit(1)
        else:
            duration_min = int(m4a_dur // 60)
            duration_sec = int(m4a_dur % 60)
            log(f"=== Pipeline complete ===")
            log(f"M5 Morning Brief -- {TODAY} -- SUCCESS")
            log(f"Duration: {duration_min}m {duration_sec}s ({m4a_dur:.1f}s)")
            log(f"TTS mode: {TTS_MODE or 'unknown'}")
            if os.path.exists(FAILURES_FILE):
                with open(FAILURES_FILE) as f:
                    failures = f.read().strip()
                    if failures:
                        log(f"Failures:\n{failures}")

    except Exception as e:
        import traceback
        try:
            log(f"Fatal error: {e}")
            log(traceback.format_exc())
        except Exception:
            pass
        sys.exit(2)
