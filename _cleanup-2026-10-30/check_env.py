#!/usr/bin/env python3
"""Check cron environment: GITHUB auth, token, release dir contents."""
import os, subprocess

# Check gh auth
r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
print("gh auth status: %s" % ("OK" if r.returncode == 0 else "NOT AUTHED"))
if r.returncode != 0:
    print(r.stderr[:300])

# Check env vars  
token_keys = ["GITHUB_TOKEN", "GH_TOKEN"]
found = []
for k in token_keys:
    v = os.environ.get(k)
    if v:
        found.append("%s=<present>" % k)
print("Token vars: %s" % str(found))

# Check release directory
rel_dir = "/Users/casper/Podcasts/M5 Morning Brief/mb-2026-10-30"
if os.path.isdir(rel_dir):
    files = os.listdir(rel_dir)
    print("\nRelease dir contents (%s):" % rel_dir)
    for f in sorted(files):
        fp = os.path.join(rel_dir, f)
        sz = os.path.getsize(fp) if os.path.isfile(fp) else "?"
        print("  %-20s %d bytes" % (f + ":", sz))
else:
    # Check parent dir to see what happened
    parent = "/Users/casper/Podcasts/M5 Morning Brief/"
    dirs = [d for d in os.listdir(parent) if os.path.isdir(os.path.join(parent, d))]
    print("\nSubdirs in Podcasts dir:", dirs)

# Check existing releases on repo  
print("\n=== Existing releases ===")
r2 = subprocess.run(["gh", "release", "list", "-R", "ronyoder31-maker/M5-Morning-Brief", "--limit", 10],
                    capture_output=True, text=True)
if r2.returncode == 0:
    print(r2.stdout)
else:
    # Try alternate spelling
    r3 = subprocess.run(["gh", "release", "list", "-R", "ronyomer31-maker/M5-Morning-Brief", "--limit", 10],
                        capture_output=True, text=True)
    if r3.returncode == 0:
        print("ronyomer31 releases:")
        print(r3.stdout)
    else:
        print("Neither repo accessible:", r2.stderr[:300] or r3.stderr[:300])
