#!/usr/bin/env bash
# setup.sh - jednorazowa instalacja venv backendu Pan Kret Studio (Linux).
# Model Qwen-Image-2.1 ma osobny venv - jego instalacja: README.md, sekcja 2.
set -e
cd "$(dirname "$0")"

if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "BLAD: brak tkinter. Zainstaluj:  sudo apt install python3-tk python3-venv"
  exit 1
fi

echo "[1/3] Tworzenie venv..."
python3 -m venv venv

echo "[2/3] Aktualizacja pip..."
./venv/bin/python -m pip install --upgrade pip

echo "[3/3] Instalacja paczek (pillow, numpy, scipy, rembg, onnxruntime, google-genai)..."
./venv/bin/pip install -r requirements.txt

chmod +x run.sh run_edit_ui.sh
echo
echo "===== GOTOWE. Uruchom ./run.sh (generowanie) albo ./run_edit_ui.sh (edycja) ====="
