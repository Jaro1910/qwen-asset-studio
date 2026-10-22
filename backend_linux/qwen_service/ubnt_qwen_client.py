#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ubnt_qwen_client.py — WERSJA LINUX (Ubuntu) klienta qwen_client.py. Windowsowe pliki
# qwen_client.py / qwen_service.py leza obok bez zmian — powrot na Windows nic nie wymaga.
# Wywolanie Qwen-Image-2.1 z dowolnego backendu (tylko biblioteka standardowa,
# wiec dziala w KAZDYM venv, bez instalowania czegokolwiek).
#
# Uzycie w backendzie (ubnt_qwen_client.py i ubnt_qwen_service.py leza w katalogu uslugi):
#   from ubnt_qwen_client import generate
#   result = generate("prompt", width=1792, height=1792)
#   result["path"]   # sciezka do wygenerowanego PNG
#   result = edit("/path/to/product.png", "the product standing on a mossy rock in a forest")
#
# Jesli usluga nie dziala, generate() sama ja uruchamia (osobny, niezalezny proces w tle,
# bez okna konsoli) i czeka az model sie zaladuje. Usluga zamyka sie sama po bezczynnosci.

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

# ---- KONFIG ----
# Usluga, venv i log leza OBOK tego pliku — dziala niezaleznie od tego, w ktorym repo sa pliki.
_HERE        = Path(__file__).resolve().parent
PYTHON_EXE   = str(_HERE / "venv-linux" / "bin" / "python")   # linuksowy venv Qwena (obok windowsowego "venv")
SERVICE_PATH = str(_HERE / "ubnt_qwen_service.py")
LOG_PATH     = str(_HERE / "ubnt_qwen_service.log")
URL          = "http://127.0.0.1:8010"   # 8000 zajmuje backend podcast-makera

START_TIMEOUT_S    = 300    # ile czekac na zaladowanie modelu po starcie uslugi
GENERATE_TIMEOUT_S = 900    # limit jednego zapytania (razem z czekaniem w kolejce)
# ----------------


class QwenError(RuntimeError):
    pass


def _status() -> str:
    """'ready' — usluga odpowiada, 'loading' — port zajety ale model sie jeszcze laduje, 'down' — nic nie nasluchuje."""
    try:
        with urllib.request.urlopen(URL + "/health", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return "ready" if data.get("status") == "ok" else "loading"
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            return "loading"
        return "down"
    except (socket.timeout, TimeoutError):
        return "loading"
    except OSError:
        return "down"


def _spawn() -> subprocess.Popen:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    kwargs = {}
    if os.name == "nt":
        # Niezalezny proces bez konsoli — przezywa backend, ktory go uruchomil.
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with open(LOG_PATH, "ab") as log:
        return subprocess.Popen(
            [PYTHON_EXE, "-u", SERVICE_PATH],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            cwd=os.path.dirname(SERVICE_PATH), close_fds=True, **kwargs,
        )


def _log_tail(lines: int = 15) -> str:
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return "(brak logu)"


def ensure_running(timeout: float = START_TIMEOUT_S) -> None:
    """Gwarantuje, ze usluga dziala i ma zaladowany model. Uruchamia ja, jesli trzeba."""
    deadline = time.time() + timeout
    proc = None
    spawns = 0
    while time.time() < deadline:
        status = _status()
        if status == "ready":
            return
        if status == "down":
            if proc is not None and proc.poll() is not None:
                if proc.returncode != 0 or spawns >= 3:
                    raise QwenError(f"Usluga Qwen nie wystartowala (kod {proc.returncode}). Koniec logu:\n{_log_tail()}")
                proc = None   # kod 0 = port byl chwilowo zajety (poprzednia instancja sie zamykala) — sprobuj ponownie
            if proc is None:
                proc = _spawn()
                spawns += 1
        time.sleep(2)
    raise QwenError(f"Usluga Qwen nie byla gotowa w ciagu {timeout:.0f} s. Koniec logu:\n{_log_tail()}")


def _post(endpoint: str, payload: dict) -> dict:
    req = urllib.request.Request(
        URL + endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=GENERATE_TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = ""
        raise QwenError(f"Qwen HTTP {e.code}: {detail}") from None


def generate(prompt: str, width: int = 1024, height: int = 1024, steps: int | None = None,
             seed: int | None = None, negative_prompt: str | None = None,
             true_cfg_scale: float | None = None) -> dict:
    """Generuje obraz. Zwraca dict: path, seed, width, height, steps, seconds.
    Parametry None sa pomijane, wiec obowiazuja domyslne z uslugi."""
    payload = {"prompt": prompt, "width": width, "height": height}
    for key, value in (("steps", steps), ("seed", seed),
                       ("negative_prompt", negative_prompt), ("true_cfg_scale", true_cfg_scale)):
        if value is not None:
            payload[key] = value

    return _call("/generate", payload)


def edit(image_path: str, prompt: str, width: int | None = None, height: int | None = None,
         steps: int | None = None, seed: int | None = None, negative_prompt: str | None = None,
         true_cfg_scale: float | None = None, strength: float | None = None) -> dict:
    """Edycja / image-to-image: obraz wejsciowy + prompt. Zwraca dict jak generate().
    width/height None = rozmiar z proporcji obrazu wejsciowego.
    QwenError z kodem 501 = model nie przyjmuje obrazu wejsciowego."""
    payload = {"image_path": os.path.abspath(image_path), "prompt": prompt}
    for key, value in (("width", width), ("height", height), ("steps", steps), ("seed", seed),
                       ("negative_prompt", negative_prompt), ("true_cfg_scale", true_cfg_scale),
                       ("strength", strength)):
        if value is not None:
            payload[key] = value
    return _call("/edit", payload)


def _call(endpoint: str, payload: dict) -> dict:
    ensure_running()
    try:
        return _post(endpoint, payload)
    except urllib.error.URLError:
        # usluga mogla sie wlasnie zamknac po bezczynnosci — uruchom ponownie i sprobuj jeszcze raz
        ensure_running()
        return _post(endpoint, payload)
