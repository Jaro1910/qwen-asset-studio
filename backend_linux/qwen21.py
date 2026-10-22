#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# qwen21.py - wspolny most do lokalnej uslugi Qwen-Image-2.1 (Linux).
# Zastepuje stable_diffusion_cpp: zamiast ladowac model w procesie, wysylamy zapytanie do
# ubnt_qwen_service.py przez ubnt_qwen_client.py (klient sam uruchamia usluge, gdy nie dziala).
# Usluga trzyma model na obu GPU i obsluguje jedno zadanie naraz (reszta czeka w kolejce).

import os, sys, threading

QWEN_DIR = os.environ.get("QWEN21_DIR", "/models/models/qwen-image-2.1")

# Limity uslugi (ubnt_qwen_service.py): kazdy bok 512-1792, podzielny przez 32.
SVC_MIN_SIDE, SVC_MAX_SIDE, SVC_MULTIPLE = 512, 1792, 32
TRUE_CFG = None              # None = domyslne uslugi (4.0); 1.0 = bez CFG (ok. 2x szybciej)
DELETE_SERVICE_COPY = True   # usluga zapisuje PNG u siebie - po wczytaniu kasujemy, wynik ladujemy w out_dir

_client = None


def client(qwen_dir=None):
    """Importuje ubnt_qwen_client z folderu Qwena (raz). Klient jest tylko na stdlib."""
    global _client
    if _client is None:
        d = qwen_dir or QWEN_DIR
        if not os.path.isfile(os.path.join(d, "ubnt_qwen_client.py")):
            raise ImportError(f"Brak ubnt_qwen_client.py w {d}")
        if d not in sys.path:
            sys.path.insert(0, d)
        import ubnt_qwen_client
        _client = ubnt_qwen_client
    return _client


def service_dims(w, h):
    """Rozmiar dla uslugi: te same proporcje co docelowe w x h, oba boki w 512-1792 i podzielne
    przez 32. Gdy wychodzi inaczej niz w x h, wynik jest potem skalowany do w x h."""
    up = max(1.0, SVC_MIN_SIDE / min(w, h))
    down = min(1.0, SVC_MAX_SIDE / (max(w, h) * up))
    s = up * down

    def snap(v):
        v = int(round(v * s / SVC_MULTIPLE)) * SVC_MULTIPLE
        return max(SVC_MIN_SIDE, min(SVC_MAX_SIDE, v))
    return snap(w), snap(h)


def _log_progress(cb, stop):
    """Usluga nie streamuje postepu - czytamy jej log i przekazujemy ostatnia linie z 'krok'."""
    log_path = client().LOG_PATH
    try:
        pos = os.path.getsize(log_path)
    except OSError:
        pos = 0
    while not stop.wait(1.0):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
        except OSError:
            continue
        for line in reversed(chunk.replace("\r", "\n").splitlines()):
            if "] krok " in line:
                cb(line[line.index("krok"):].strip())
                break


def _run(call, w, h, progress_cb):
    from PIL import Image
    stop = threading.Event()
    t = None
    if progress_cb:
        t = threading.Thread(target=_log_progress, args=(progress_cb, stop), daemon=True)
        t.start()
    try:
        res = call()
    finally:
        stop.set()
        if t:
            t.join(timeout=2)
    path = res["path"]
    img = Image.open(path)
    img.load()
    if DELETE_SERVICE_COPY:
        try: os.remove(path)
        except OSError: pass
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    return img, res


def generate(prompt, negative, w, h, steps, seed=None, progress_cb=None):
    """Text-to-image. Zwraca (PIL.Image o rozmiarze w x h, odpowiedz uslugi)."""
    c = client()
    sw, sh = service_dims(w, h)
    if seed is not None:
        seed = int(seed) & 0xFFFFFFFF
    return _run(lambda: c.generate(prompt, width=sw, height=sh, steps=steps, seed=seed,
                                   negative_prompt=negative or None, true_cfg_scale=TRUE_CFG),
                w, h, progress_cb)


def edit(image_path, prompt, w, h, steps, seed=None, negative=None, progress_cb=None):
    """Edycja z obrazem referencyjnym. Zwraca (PIL.Image o rozmiarze w x h, odpowiedz uslugi)."""
    c = client()
    sw, sh = service_dims(w, h)
    if seed is not None:
        seed = int(seed) & 0xFFFFFFFF
    return _run(lambda: c.edit(image_path, prompt, width=sw, height=sh, steps=steps, seed=seed,
                               negative_prompt=negative or None, true_cfg_scale=TRUE_CFG),
                w, h, progress_cb)
