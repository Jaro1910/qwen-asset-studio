#!/usr/bin/env bash
# run.sh - Pan Kret Studio (generowanie). Log leci na ekran i do studio_log.txt.
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then echo "Najpierw uruchom ./setup.sh"; exit 1; fi
echo "Uruchamiam Pan Kret Studio... pelny log leci do studio_log.txt"
./venv/bin/python -u pan_kret_studio.py 2>&1 | tee studio_log.txt
