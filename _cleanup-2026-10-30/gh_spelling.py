#!/usr/bin/env python3
"""Test each spelling for repo access."""
import subprocess, sys

spellings = [
    "ronyomer31-maker/M5-Morning-Brief",
    "ronyoder31-maker/M5-Morning-Brief", 
    "ronyder31-maker/M5-Morning-Brief",
]

for spell in spellings:
    r = subprocess.run(["gh", "release", "list", "-R", spell, "--limit", 1],
                      capture_output=True, text=True)
    status = "OK" if r.returncode == 0 else "FAIL"
    out = r.stdout.strip()[:60] if r.returncode == 0 else r.stderr.strip()[:80]
    print(f"{status} | {spell}")
    if r.returncode != 0:
        # Try without -R, using GH_REPO env var
        env = dict(sys.environ or {}, **{"GH_REPO": spell})
        r2 = subprocess.run(["gh", "release", "list"], capture_output=True, text=True, env=env)
        status2 = "OK" if r2.returncode == 0 else "FAIL"
        out2 = r2.stdout.strip()[:60] if r2.returncode == 0 else r2.stderr.strip()[:80]
        print(f"      GH_REPO: {status2} | {out2}")
