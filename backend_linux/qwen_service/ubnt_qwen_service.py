#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ubnt_qwen_service.py — WERSJA LINUX (Ubuntu) uslugi qwen_service.py (te same wagi, ten sam port).
# Usluga HTTP (FastAPI) dla Qwen-Image-2.1.
# Model laduje sie RAZ przy starcie, backendy wysylaja zapytania na localhost.
#
# NIE uruchamiasz jej recznie: startuje ja ubnt_qwen_client.py (na zawolane z backendu)
# i sama sie zamyka po IDLE_TIMEOUT_MIN minutach bez zapytan, zwalniajac GPU.
# Reczny start (opcjonalnie), z folderu, w ktorym lezy ten plik:
#   ./venv-linux/bin/python ubnt_qwen_service.py
# Jednorazowo w venv Qwena:
#   pip install fastapi uvicorn

import gc
import inspect
import os
import random
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager

HOST, PORT = "127.0.0.1", 8010   # 8000 zajmuje backend podcast-makera
BIND_WAIT_S = 20   # ile sekund czekac na zwolnienie portu (np. gdy poprzednia instancja wlasnie sie zamyka)


def _bind_port():
    """Zajmuje port. Zwraca gniazdo albo None, jesli port jest zajety dluzej niz BIND_WAIT_S."""
    deadline = time.time() + BIND_WAIT_S
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # Linux/macOS: pozwala od razu zajac port po zamknieciu poprzedniej instancji.
            # Na Windowsie CELOWO bez tego — tam SO_REUSEADDR pozwalalby zajac ten sam port dwa razy.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
            return s
        except OSError:
            s.close()
            if time.time() > deadline:
                return None
            time.sleep(1)


# Port zajmujemy OD RAZU, jeszcze przed importem torcha i ladowaniem 30 GB wag. Drugi start, gdy usluga
# juz dziala albo sie laduje, konczy sie tu bez dotykania GPU. Polaczenia w trakcie ladowania modelu
# czekaja w kolejce gniazda.
_sock = None
if __name__ == "__main__":
    _sock = _bind_port()
    if _sock is None:
        print(f"Port {PORT} zajety — usluga juz dziala lub sie laduje. Koncze.", flush=True)
        sys.exit(0)
    _sock.listen(2048)

import torch  # noqa: E402  (importy po zajeciu portu — celowo)
import uvicorn  # noqa: E402
from diffusers import QwenImage21Pipeline  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from PIL import Image  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

# ---- KONFIG ----
MODEL_DIR = "/models/models/qwen-image-2.1"                  # lokalny folder z wagami (NVMe)
OUT_DIR   = os.path.expanduser("~/backends/output/qwen2.1")   # tu zapisywane sa wygenerowane obrazy
# HOST i PORT sa ustawione na gorze pliku (port zajmowany przed ladowaniem modelu)

# Steruje tylko ROZMIESZCZENIEM komponentow, nie limitem pamieci w czasie pracy:
# text_encoder -> cuda:1 (3080), transformer + vae -> cuda:0 (3090).
MAX_MEMORY = {0: "18GB", 1: "22GB"}

MIN_SIDE, MAX_SIDE = 512, 1792     # dozwolony zakres dla kazdego boku
SIDE_MULTIPLE      = 32            # pipeline wymaga podzielnosci przez 32
DEFAULT_STEPS      = 25
DEFAULT_TRUE_CFG   = 4.0
USE_KV_CACHE       = False         # wbudowany cache modelu — wylaczony

# Po ilu minutach bez zapytan usluga sie zamyka i zwalnia GPU (0 = nigdy).
IDLE_TIMEOUT_MIN = float(os.environ.get("QWEN_IDLE_MIN", "10"))

# Dluzszy bok powyzej tej wartosci -> VAE dekoduje kaflami (mniej pamieci, ryzyko delikatnych szwow).
# Do 1024 VAE dekoduje caly obraz naraz (tak dzialal test 1024x1024).
VAE_TILING_ABOVE = 1024
VAE_TILE = dict(
    tile_sample_min_height=512, tile_sample_min_width=512,
    tile_sample_stride_height=384, tile_sample_stride_width=384,
)
# ----------------

state = {}
gpu_lock = threading.Lock()   # jedno zadanie naraz na GPU, reszta czeka w kolejce


def idle_watcher(server: uvicorn.Server):
    limit = IDLE_TIMEOUT_MIN * 60
    interval = max(1.0, min(15.0, limit / 4))
    while not server.should_exit:
        time.sleep(interval)
        if gpu_lock.locked():
            continue
        if time.monotonic() - state.get("last_activity", time.monotonic()) > limit:
            print(f"Bezczynnosc > {IDLE_TIMEOUT_MIN} min — zamykam usluge i zwalniam GPU.", flush=True)
            server.should_exit = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Ladowanie modelu Qwen-Image-2.1...", flush=True)
    pipe = QwenImage21Pipeline.from_pretrained(
        MODEL_DIR, torch_dtype=torch.bfloat16,
        device_map="balanced", max_memory=MAX_MEMORY,
    )
    print("Rozklad komponentow na GPU:", pipe.hf_device_map, flush=True)
    # Czy pipeline przyjmuje obraz wejsciowy (edycja / image-to-image)?
    # Sprawdzamy sygnature zamiast zgadywac — /edit odpowiada 501, gdy nie.
    call_params = set(inspect.signature(pipe.__call__).parameters)
    state["edit_params"] = sorted(p for p in ("image", "strength") if p in call_params)
    print("Parametry edycji obrazu w pipeline:", state["edit_params"] or "BRAK", flush=True)
    # Log postepu per krok — tylko jesli pipeline ma callback (inaczej log bez krokow).
    state["step_log"] = "callback_on_step_end" in call_params
    state["pipe"] = pipe
    state["last_activity"] = time.monotonic()
    if IDLE_TIMEOUT_MIN > 0 and "server" in state:
        threading.Thread(target=idle_watcher, args=(state["server"],), daemon=True).start()
    print(f"Usluga gotowa: http://{HOST}:{PORT}", flush=True)
    yield
    state.clear()


app = FastAPI(title="Qwen-Image-2.1 service", lifespan=lifespan)


def _check_side(v: int) -> int:
    if v < MIN_SIDE or v > MAX_SIDE:
        raise ValueError(f"musi byc w zakresie {MIN_SIDE}-{MAX_SIDE}")
    if v % SIDE_MULTIPLE:
        raise ValueError(f"musi byc podzielne przez {SIDE_MULTIPLE}")
    return v


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    negative_prompt: str = " "                       # pusty string nie wlacza true CFG, wiec zamieniamy na " "
    width: int = 1024
    height: int = 1024
    steps: int = Field(DEFAULT_STEPS, ge=1, le=100)
    true_cfg_scale: float = Field(DEFAULT_TRUE_CFG, ge=1.0, le=20.0)   # 1.0 = bez CFG (okolo 2x szybciej)
    seed: int | None = Field(None, ge=0, le=2**32 - 1)                  # brak = losowy

    @field_validator("width", "height")
    @classmethod
    def check_side(cls, v: int) -> int:
        return _check_side(v)


class EditRequest(BaseModel):
    image_path: str = Field(min_length=1)            # plik na tym samym komputerze (usluga dziala na localhost)
    prompt: str = Field(min_length=1)
    negative_prompt: str = " "
    width: int | None = None                         # brak = z proporcji obrazu wejsciowego
    height: int | None = None
    steps: int = Field(DEFAULT_STEPS, ge=1, le=100)
    true_cfg_scale: float = Field(DEFAULT_TRUE_CFG, ge=1.0, le=20.0)
    strength: float | None = Field(None, gt=0.0, le=1.0)   # tylko jesli pipeline ma parametr strength
    seed: int | None = Field(None, ge=0, le=2**32 - 1)

    @field_validator("width", "height")
    @classmethod
    def check_side(cls, v: int | None) -> int | None:
        return None if v is None else _check_side(v)


def _fit_size(w: int, h: int) -> tuple[int, int]:
    """Rozmiar wyjscia z proporcji obrazu wejsciowego: dluzszy bok najwyzej
    1024 (do tej granicy VAE dekoduje bez kafli), oba boki w limicie i
    podzielne przez SIDE_MULTIPLE."""
    scale = min(1.0, 1024 / max(w, h))
    def snap(v: float) -> int:
        v = int(round(v / SIDE_MULTIPLE)) * SIDE_MULTIPLE
        return max(MIN_SIDE, min(MAX_SIDE, v))
    return snap(w * scale), snap(h * scale)


def _step_kwargs(tag: str, total: int) -> dict:
    """Callback wypisujacy do logu kazdy krok: numer, czas kroku, szacowany koniec."""
    if not state.get("step_log"):
        return {}
    t_start = time.time()
    last = [t_start]

    def on_step_end(pipe, step, timestep, callback_kwargs):
        now = time.time()
        done = step + 1
        per_step = (now - t_start) / done
        print(f"[{tag}] krok {done}/{total}  {now - last[0]:.1f} s/krok  "
              f"(zostalo ~{per_step * (total - done):.0f} s)", flush=True)
        last[0] = now
        return callback_kwargs

    return {"callback_on_step_end": on_step_end}


def free_gpu_memory():
    gc.collect()
    for i in range(torch.cuda.device_count()):
        with torch.cuda.device(i):
            torch.cuda.empty_cache()


@app.get("/health")
def health():
    ready = "pipe" in state
    return {
        "status": "ok" if ready else "loading",
        "device_map": state["pipe"].hf_device_map if ready else None,
        "edit_params": state.get("edit_params") if ready else None,
        "min_side": MIN_SIDE, "max_side": MAX_SIDE, "side_multiple": SIDE_MULTIPLE,
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    pipe = state["pipe"]
    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    state["last_activity"] = time.monotonic()

    with gpu_lock:
        t0 = time.time()
        print(f"[generate] start: {req.width}x{req.height}, {req.steps} krokow, "
              f"cfg {req.true_cfg_scale}, seed {seed}", flush=True)
        try:
            if max(req.width, req.height) > VAE_TILING_ABOVE:
                pipe.vae.enable_tiling(**VAE_TILE)
            else:
                pipe.vae.disable_tiling()

            image = pipe(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt or " ",
                true_cfg_scale=req.true_cfg_scale,
                width=req.width, height=req.height,
                num_inference_steps=req.steps,
                generator=torch.Generator("cuda").manual_seed(seed),
                use_kv_cache=USE_KV_CACHE,
                **_step_kwargs("generate", req.steps),
            ).images[0]
        except torch.OutOfMemoryError:
            raise HTTPException(status_code=507, detail="Brak pamieci GPU dla tej rozdzielczosci — zmniejsz width/height.")
        finally:
            free_gpu_memory()
            state["last_activity"] = time.monotonic()

        seconds = round(time.time() - t0, 1)
        filename = f"qwen21_{time.strftime('%Y%m%d_%H%M%S')}_{seed}_{req.width}x{req.height}.png"
        path = os.path.join(OUT_DIR, filename)
        image.save(path)
        print(f"Gotowe w {seconds} s: {path}", flush=True)

    return {
        "path": path, "seed": seed,
        "width": req.width, "height": req.height,
        "steps": req.steps, "seconds": seconds,
    }


@app.post("/edit")
def edit(req: EditRequest):
    """Generuje obraz na podstawie obrazu wejsciowego i promptu (edycja /
    image-to-image). Wymaga, zeby pipeline przyjmowal parametr image —
    inaczej 501 (patrz /health -> edit_params)."""
    pipe = state["pipe"]
    edit_params = state.get("edit_params") or []
    if "image" not in edit_params:
        raise HTTPException(status_code=501, detail="Ten pipeline nie przyjmuje obrazu wejsciowego (brak parametru image).")
    if req.strength is not None and "strength" not in edit_params:
        raise HTTPException(status_code=422, detail="Ten pipeline nie ma parametru strength — usun go z zapytania.")
    if not os.path.isfile(req.image_path):
        raise HTTPException(status_code=404, detail=f"Brak pliku: {req.image_path}")
    try:
        src = Image.open(req.image_path).convert("RGB")
    except OSError as e:
        raise HTTPException(status_code=422, detail=f"Nie da sie otworzyc obrazu: {e}")

    if req.width is None or req.height is None:
        width, height = _fit_size(*src.size)
    else:
        width, height = req.width, req.height
    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    state["last_activity"] = time.monotonic()

    extra = {"strength": req.strength} if req.strength is not None else {}
    with gpu_lock:
        t0 = time.time()
        print(f"[edit] start: {os.path.basename(req.image_path)} -> {width}x{height}, "
              f"{req.steps} krokow, cfg {req.true_cfg_scale}, seed {seed}", flush=True)
        try:
            if max(width, height) > VAE_TILING_ABOVE:
                pipe.vae.enable_tiling(**VAE_TILE)
            else:
                pipe.vae.disable_tiling()

            image = pipe(
                image=src,
                prompt=req.prompt,
                negative_prompt=req.negative_prompt or " ",
                true_cfg_scale=req.true_cfg_scale,
                width=width, height=height,
                num_inference_steps=req.steps,
                generator=torch.Generator("cuda").manual_seed(seed),
                use_kv_cache=USE_KV_CACHE,
                **extra,
                **_step_kwargs("edit", req.steps),
            ).images[0]
        except torch.OutOfMemoryError:
            raise HTTPException(status_code=507, detail="Brak pamieci GPU dla tej rozdzielczosci — zmniejsz width/height.")
        finally:
            free_gpu_memory()
            state["last_activity"] = time.monotonic()

        seconds = round(time.time() - t0, 1)
        filename = f"qwen21_edit_{time.strftime('%Y%m%d_%H%M%S')}_{seed}_{width}x{height}.png"
        path = os.path.join(OUT_DIR, filename)
        image.save(path)
        print(f"Gotowe w {seconds} s: {path}", flush=True)

    return {
        "path": path, "seed": seed,
        "width": width, "height": height,
        "steps": req.steps, "seconds": seconds,
    }


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="info"))
    state["server"] = server
    server.run(sockets=[_sock])
