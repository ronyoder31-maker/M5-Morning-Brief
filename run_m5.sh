#!/usr/bin/env bash
# M5 Morning Brief — launcher (uses Python 3.12 with edge_tts installed)
PYTHON=/opt/homebrew/opt/python@3.12/bin/python3.12
LOGFILE="/Users/casper/.hermes/cache/scratch/m5_run_$$.log"

exec "$PYTHON" /Users/casper/M5-Morning-Brief/m5-pipeline.py >"$LOGFILE" 2>&1
