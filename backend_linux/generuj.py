#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# generuj.py (LINUX) - generuje grafiki z pliku z promptami (PROMPTS_JSON) przez Qwen-Image-2.1 (usluga, patrz qwen21.py)
# Odpal:  ./venv/bin/python generuj.py

import json, os

import qwen21
import tlo
from jezyk import t, postep

# ---- KONFIG ----
_HERE           = os.path.dirname(os.path.abspath(__file__))
PROMPTS_JSON    = os.path.join(os.path.dirname(_HERE), "01_common_ui.json")   # dowolny plik z promptami
OUT_DIR         = os.path.expanduser("~/backends/output/pan-kret-studio")
STEPS           = 24
USE_REMBG       = True   # ratunek, gdy chroma key zawiedzie (tlo nie bylo zielone) - patrz tlo.py
USE_CHROMA      = True   # wycinanie jednolitej zieleni (szybsze/pewniejsze niz rembg)
SEED            = None   # np. 1410; None = losowo
SEED_GROUP_FIELD = ""    # np. "god" / "scene" / "unit_class" -> spojne rodziny sprite'ow
DEFAULT_NEGATIVE = "text, letters, words, typography, watermark, signature, logo, caption, subtitles, numbers, UI text"
AR = {"1:1": (1024, 1024), "16:9": (1280, 720)}
MAX_SIDE, MIN_SIDE = 1440, 256


def asset_dims(a):
    import math
    res = str(a.get("resolution", "") or "")
    w = h = None
    if "x" in res.lower():
        try: w, h = [int(v) for v in res.lower().split("x")[:2]]
        except ValueError: w = h = None
    if w is None:
        ar = str(a.get("aspect_ratio", "1:1"))
        if ar in AR: w, h = AR[ar]
        else:
            try: rw, rh = [float(v) for v in ar.split(":")]
            except Exception: rw = rh = 1.0
            w = int(math.sqrt(1024*1024*rw/rh)); h = int(math.sqrt(1024*1024*rh/rw))
    sc = min(1.0, MAX_SIDE/max(w, h)); w, h = int(w*sc), int(h*sc)
    return max(MIN_SIDE, (w//16)*16), max(MIN_SIDE, (h//16)*16)


def group_seed(a):
    import zlib
    if a.get("seed") is not None:
        try: return int(a["seed"])
        except (TypeError, ValueError): pass
    if SEED is None: return None
    if SEED_GROUP_FIELD and a.get(SEED_GROUP_FIELD):
        return int(SEED) + (zlib.crc32(str(a[SEED_GROUP_FIELD]).encode()) % 100000)
    return int(SEED)


# ----------------


data = json.load(open(PROMPTS_JSON, encoding="utf-8"))
assets = data.get("assets") or data.get("prompts") or []
negative = data.get("global", {}).get("negative", "") or data.get("negative", "")
os.makedirs(OUT_DIR, exist_ok=True)

print(t("Usluga Qwen-Image-2.1 - sprawdzam / uruchamiam..."))
qwen21.client().ensure_running()

total = len(assets)
for i, a in enumerate(assets, 1):
    out_path = os.path.join(OUT_DIR, a["id"] + ".png")
    if os.path.exists(out_path):
        print(f"[{i}/{total}] {a['id']} - " + t("pomijam (jest)"))
        continue
    w, h = asset_dims(a)
    print(f"[{i}/{total}] {a['id']} ({w}x{h}) ...")

    neg = (a.get("negative") or "").strip() or (negative or "").strip() or DEFAULT_NEGATIVE
    img, _ = qwen21.generate(tlo.sanitize_prompt(a["prompt"]), neg, w, h, STEPS, seed=group_seed(a),
                             progress_cb=lambda txt: print(f"      {postep(txt)}", end="\r"))

    if "transparent" in str(a.get("background", "")).lower():
        raw = os.path.join(OUT_DIR, "_raw_" + a["id"] + ".png")
        img.save(raw)
        used = tlo.wytnij_tlo(raw, out_path, ("chroma", "rembg"), chroma=USE_CHROMA, rembg=USE_REMBG,
                              log=lambda tekst: print(f"      {tekst}"))
        if used:
            print("      " + t("tlo wyciete ({narzedzie})", narzedzie=used))
        os.remove(raw)
    else:
        img.save(out_path)
    print("      " + t("zapisano {plik}", plik=out_path))

print(t("Gotowe."))
