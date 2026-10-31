#!/bin/bash
# M5 Morning Brief runner — always uses Kokoro venv Python with clean env.
# Do NOT edit the LaunchAgent directly; use: launchctl unload/load com.ronyoder.m5-morning-brief-daily

set -euo pipefail

ENV=/Users/casper/AI/Kokoro/venv/bin/python
SCRIPT=/Users/casper/M5-Morning-Brief/m5-morning-brief.py

exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV "$ENV" "$SCRIPT"
