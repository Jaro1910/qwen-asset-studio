#!/usr/bin/env bash
# run_edit_ui.sh - Pan Kret Edit Studio (edycja obrazow z referencja).
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then echo "Najpierw uruchom ./setup.sh"; exit 1; fi
./venv/bin/python pan_kret_edit_studio.py
