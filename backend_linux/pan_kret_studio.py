#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Pan Kret Studio (LINUX) - GUI do generowania grafik z plikow z promptami (*.json)
# Lokalnie: Qwen-Image-2.1 przez usluge ubnt_qwen_service.py (patrz qwen21.py). Tryb API: Gemini.
# Uruchom: ./run.sh

import json, os, queue, threading, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import qwen21
import tlo
import jezyk
from jezyk import t

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULT_CFG = {
    "qwen_dir": qwen21.QWEN_DIR,                 # folder z ubnt_qwen_client.py / ubnt_qwen_service.py
    "prompts_json": os.path.join(REPO_DIR, "01_common_ui.json"),
    "out_dir": os.path.expanduser("~/backends/output/pan-kret-studio"),
    "steps": 24, "seed": "", "use_rembg": True, "use_chroma": True,
    "seed_group_field": "", "category_subdirs": False,
    "default_negative": "text, letters, words, typography, watermark, signature, logo, caption, subtitles, numbers, UI text, frame border text",
    # --- zrodlo generowania: lokalny model albo API ---
    "gen_mode": "local",                        # "local" | "api"
    "api_key": "",                              # klucz z aistudio.google.com (trzymany lokalnie w config.json)
    "api_model": "gemini-2.5-flash-image",       # "Nano Banana"; nowszy wariant: gemini-3.1-flash-image
    "api_delay": 4,                              # sekundy pauzy miedzy zapytaniami (limity darmowego tieru)
}
_API_ASPECT_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
AR_DIMS = {"1:1": (1024, 1024), "16:9": (1280, 720)}
DEFAULT_DIMS = (1024, 1024)
MAX_SIDE = 1440   # Qwen-Image: powyzej zaczyna gubic kompozycje / zjadac VRAM
MIN_SIDE = 256


def asset_dims(a):
    """Wymiary z pola 'resolution' (np. '768x1024') lub dowolnego aspect_ratio 'W:H'.
    Zaokragla do wielokrotnosci 16, pilnuje MIN/MAX_SIDE. To rozmiar PLIKU WYNIKOWEGO -
    rozmiar dla uslugi Qwen 2.1 (512-1792, /32) liczy qwen21.service_dims."""
    import math
    w = h = None
    res = str(a.get("resolution", "") or "")
    if "x" in res.lower():
        try:
            w, h = [int(v) for v in res.lower().split("x")[:2]]
        except ValueError:
            w = h = None
    if w is None:
        ar = str(a.get("aspect_ratio", "1:1"))
        if ar in AR_DIMS:
            w, h = AR_DIMS[ar]
        else:
            try:
                rw, rh = [float(v) for v in ar.split(":")]
            except Exception:
                rw = rh = 1.0
            area = 1024 * 1024
            w = int(math.sqrt(area * rw / rh))
            h = int(math.sqrt(area * rh / rw))
    scale = min(1.0, MAX_SIDE / max(w, h))
    w, h = int(w * scale), int(h * scale)
    w = max(MIN_SIDE, (w // 16) * 16)
    h = max(MIN_SIDE, (h // 16) * 16)
    return w, h


def nearest_aspect_ratio(w, h):
    """Gemini image API przyjmuje proporcje z ustalonej listy, nie dowolne px.
    Dobiera najblizszy format do docelowego w:h z manifestu."""
    import math
    target = (w / h) if h else 1.0
    best, best_diff = "1:1", float("inf")
    for r in _API_ASPECT_RATIOS:
        rw, rh = r.split(":")
        diff = abs(math.log((float(rw) / float(rh)) / target))
        if diff < best_diff:
            best_diff, best = diff, r
    return best


def group_seed(base_seed, a, field):
    """Spojnosc rodzin (np. 12 sprite'ow jednego boga): seed = baza + hash(pola grupy).
    Per-asset 'seed' w manifescie ma najwyzszy priorytet."""
    import zlib
    if a.get("seed") is not None:
        try:
            return int(a["seed"])
        except (TypeError, ValueError):
            pass
    if base_seed is None:
        return None
    if field and a.get(field):
        return int(base_seed) + (zlib.crc32(str(a[field]).encode()) % 100000)
    return int(base_seed)


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CONFIG_PATH):
        try:
            cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_cfg(cfg):
    json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pan Kret Studio")
        self.geometry("1000x700")
        self.cfg = load_cfg()
        self.assets = []
        self.negative = ""
        self.msg_q = queue.Queue()
        self.worker = None
        self.stop_flag = threading.Event()
        self._genai_client = None
        self._preview_img = None
        self._build_ui()
        self._load_assets(silent=True)
        self.after(100, self._poll_queue)

    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Button(bar, text=t("Jezyk: PL"), command=self._przelacz_jezyk).pack(side="right")
        mode_frame = ttk.LabelFrame(self, text=t("Zrodlo generowania"))
        mode_frame.pack(fill="x", padx=8, pady=(2, 0))
        self.mode_var = tk.StringVar(value=str(self.cfg.get("gen_mode", "local")))
        mrow = ttk.Frame(mode_frame)
        mrow.pack(fill="x", padx=4, pady=4)
        ttk.Radiobutton(mrow, text=t("Lokalnie (Qwen-Image-2.1 / usluga)"), value="local",
                        variable=self.mode_var, command=self._on_mode_change).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(mrow, text=t("API (Google AI Studio - Gemini)"), value="api",
                        variable=self.mode_var, command=self._on_mode_change).pack(side="left")

        self.api_frame = ttk.Frame(mode_frame)
        self.apikey_var = tk.StringVar(value=str(self.cfg.get("api_key", "")))
        ttk.Label(self.api_frame, text=t("Klucz API:"), width=18).grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.apikey_entry = ttk.Entry(self.api_frame, textvariable=self.apikey_var, width=50, show="*")
        self.apikey_entry.grid(row=0, column=1, sticky="we", padx=4)
        self.apikey_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.api_frame, text=t("pokaz"), variable=self.apikey_show,
                        command=self._toggle_apikey_visibility).grid(row=0, column=2, padx=4, sticky="w")
        ttk.Label(self.api_frame, text=t("Model:"), width=18).grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.apimodel_var = tk.StringVar(value=str(self.cfg.get("api_model", "gemini-2.5-flash-image")))
        ttk.Entry(self.api_frame, textvariable=self.apimodel_var, width=50).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(self.api_frame, text=t("Opoznienie miedzy zapytaniami (s):"), width=28).grid(
            row=2, column=0, sticky="w", padx=4, pady=2)
        self.apidelay_var = tk.StringVar(value=str(self.cfg.get("api_delay", 4)))
        ttk.Entry(self.api_frame, textvariable=self.apidelay_var, width=6).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(self.api_frame,
                  text=t("Klucz zdobedziesz na aistudio.google.com -> 'Get API key'. Trzymany lokalnie w config.json - nie wrzucaj go do gita."),
                  foreground="#888").grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 4))
        self.api_frame.columnconfigure(1, weight=1)

        top = ttk.LabelFrame(self, text=t("Ustawienia"))
        top.pack(fill="x", padx=8, pady=6)
        self.vars = {}
        rows = [
            ("qwen_dir", "Qwen-Image-2.1 (folder)", "dir"),
            ("prompts_json", "Prompty (.json)", "file"),
            ("out_dir", "Folder wyjsciowy", "dir"),
        ]
        local_only_keys = ("qwen_dir",)
        self._local_only_widgets = []
        for i, (key, label, browse) in enumerate(rows):
            ttk.Label(top, text=t(label), width=24).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            v = tk.StringVar(value=str(self.cfg.get(key, "")))
            self.vars[key] = v
            entry = ttk.Entry(top, textvariable=v, width=78)
            entry.grid(row=i, column=1, sticky="we", padx=4)
            btn = ttk.Button(top, text="...", width=3,
                              command=lambda k=key, b=browse: self._browse(k, b))
            btn.grid(row=i, column=2, padx=4)
            if key in local_only_keys:
                self._local_only_widgets += [entry, btn]
        top.columnconfigure(1, weight=1)

        opts = ttk.Frame(top)
        opts.grid(row=len(rows), column=0, columnspan=3, sticky="w", padx=4, pady=4)
        self.steps_var = tk.IntVar(value=int(self.cfg.get("steps", 24)))
        ttk.Label(opts, text=t("Kroki:")).pack(side="left")
        ttk.Spinbox(opts, from_=4, to=80, textvariable=self.steps_var, width=5).pack(side="left", padx=(2, 10))
        ttk.Label(opts, text=t("Seed:")).pack(side="left")
        self.seed_var = tk.StringVar(value=str(self.cfg.get("seed", "")))
        ttk.Entry(opts, textvariable=self.seed_var, width=10).pack(side="left", padx=(2, 10))
        self.chroma_var = tk.BooleanVar(value=bool(self.cfg.get("use_chroma", True)))
        ttk.Checkbutton(opts, text=t("Chroma key (zielone)"), variable=self.chroma_var).pack(side="left", padx=6)
        self.rembg_var = tk.BooleanVar(value=bool(self.cfg.get("use_rembg", True)))
        ttk.Checkbutton(opts, text=t("rembg (fallback)"), variable=self.rembg_var).pack(side="left", padx=6)
        ttk.Label(opts, text=t("Seed grupy z pola:")).pack(side="left", padx=(8, 0))
        self.group_var = tk.StringVar(value=str(self.cfg.get("seed_group_field", "")))
        ttk.Entry(opts, textvariable=self.group_var, width=10).pack(side="left", padx=(2, 6))
        self.subdir_var = tk.BooleanVar(value=bool(self.cfg.get("category_subdirs", False)))
        ttk.Checkbutton(opts, text=t("Podfoldery kategorii"), variable=self.subdir_var).pack(side="left", padx=4)
        # (offload / VAE / CLIP na CPU / max VRAM / GPU: rozklad na karty ustawia teraz usluga Qwen 2.1)
        akcje = ttk.Frame(top)   # osobny rzad: w jednym z opcjami przyciski wychodzily poza okno
        akcje.grid(row=len(rows) + 1, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))
        ttk.Button(akcje, text=t("Zapisz ustawienia"), command=self._save_settings).pack(side="left")
        ttk.Button(akcje, text=t("Wczytaj prompty..."), command=self._pick_prompts).pack(side="left", padx=6)
        ttk.Button(akcje, text=t("Przeladuj liste"), command=self._load_assets).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        cols = ("id", "kategoria", "status")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (220, 110, 130)):
            self.tree.heading(c, text=t(c))
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.LabelFrame(mid, text=t("Podglad"))
        right.pack(side="left", fill="both", padx=(8, 0))
        self.preview = ttk.Label(right, text=t("(brak)"), width=46, anchor="center")
        self.preview.pack(fill="both", expand=True, padx=6, pady=6)

        bottom = ttk.Frame(self)
        bottom.pack(fill="both", padx=8, pady=6)
        btns = ttk.Frame(bottom)
        btns.pack(fill="x")
        self.btn_sel = ttk.Button(btns, text=t("Generuj zaznaczone"), command=lambda: self._start(False))
        self.btn_sel.pack(side="left")
        self.btn_all = ttk.Button(btns, text=t("Generuj brakujace"), command=lambda: self._start(True))
        self.btn_all.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(btns, text=t("Stop (po biezacym)"), command=self._stop, state="disabled")
        self.btn_stop.pack(side="left")
        self.progress = ttk.Label(btns, text="")
        self.progress.pack(side="right")
        self.log = tk.Text(bottom, height=10, wrap="word", bg="#101010", fg="#d0d0d0")
        self.log.pack(fill="both", expand=True, pady=(6, 0))

        self._on_mode_change()

    def _toggle_apikey_visibility(self):
        self.apikey_entry.config(show="" if self.apikey_show.get() else "*")

    def _on_mode_change(self):
        is_api = self.mode_var.get() == "api"
        if is_api:
            self.api_frame.pack(fill="x", padx=4, pady=(0, 4))
        else:
            self.api_frame.pack_forget()
        state = "disabled" if is_api else "normal"
        for w in self._local_only_widgets:
            try:
                w.config(state=state)
            except tk.TclError:
                pass

    def _browse(self, key, kind):
        p = filedialog.askdirectory() if kind == "dir" else filedialog.askopenfilename()
        if p:
            self.vars[key].set(p)
            if key == "prompts_json":
                self._load_assets()

    def _save_settings(self):
        self._pola_do_cfg()
        save_cfg(self.cfg)
        self._log(t("Zapisano ustawienia."))

    def _pola_do_cfg(self):
        """Przepisuje pola okna do self.cfg (bez zapisu na dysk)."""
        for k, v in self.vars.items():
            self.cfg[k] = v.get()
        self.cfg["steps"] = int(self.steps_var.get())
        self.cfg["seed"] = self.seed_var.get().strip()
        self.cfg["use_rembg"] = bool(self.rembg_var.get())
        self.cfg["use_chroma"] = bool(self.chroma_var.get())
        self.cfg["seed_group_field"] = self.group_var.get().strip()
        self.cfg["category_subdirs"] = bool(self.subdir_var.get())
        self.cfg["gen_mode"] = self.mode_var.get()
        self.cfg["api_key"] = self.apikey_var.get().strip()
        self.cfg["api_model"] = self.apimodel_var.get().strip()
        self.cfg["api_delay"] = self.apidelay_var.get().strip()

    def _przelacz_jezyk(self):
        """PL <-> EN od razu: okno budowane od nowa, pola, lista i log zostaja."""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(t("Trwa generowanie"), t("Jezyk zmienisz po zakonczeniu generowania."))
            return
        self._pola_do_cfg()
        log = self.log.get("1.0", "end-1c")
        jezyk.ustaw("en" if jezyk.kod() == "pl" else "pl")
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        self._load_assets(silent=True)
        self.log.delete("1.0", "end")
        self.log.insert("1.0", log + "\n")
        self.log.see("end")

    def _load_assets(self, silent=False):
        path = self.vars["prompts_json"].get()
        if not os.path.exists(path):
            if not silent:
                messagebox.showwarning(t("Brak pliku"), t("Nie znaleziono:\n{path}", path=path))
            return
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            if not silent:
                messagebox.showerror(t("Blad JSON"), t("Nie udalo sie wczytac:\n{e}", e=e))
            return
        # obsluga obu schematow: {"assets":[...]} oraz {"prompts":[...]}
        self.assets = data.get("assets") or data.get("prompts") or []
        self.negative = data.get("global", {}).get("negative", "") or data.get("negative", "")
        self.tree.delete(*self.tree.get_children())
        out_dir = self.vars["out_dir"].get()
        for a in self.assets:
            done = os.path.exists(os.path.join(out_dir, a["id"] + ".png")) or \
                (a.get("category") and os.path.exists(os.path.join(out_dir, str(a["category"]), a["id"] + ".png")))
            self.tree.insert("", "end", iid=a["id"],
                             values=(a["id"], a.get("category", ""), t("zrobione") if done else t("czeka")))
        self._log(t("Wczytano {n} promptow z {plik}.", n=len(self.assets), plik=os.path.basename(path)))

    def _pick_prompts(self):
        p = filedialog.askopenfilename(title=t("Wybierz plik z promptami"),
                                       filetypes=[("JSON", "*.json"), (t("Wszystkie pliki"), "*.*")])
        if p:
            self.vars["prompts_json"].set(p)
            self._load_assets()

    def _asset_by_id(self, aid):
        for a in self.assets:
            if a["id"] == aid:
                return a
        return None

    def _on_select(self, _e):
        sel = self.tree.selection()
        if sel:
            self._show_preview(sel[-1])

    def _out_path_for(self, a):
        base = self.vars["out_dir"].get()
        if bool(self.cfg.get("category_subdirs", False)) and a and a.get("category"):
            return os.path.join(base, str(a["category"]), a["id"] + ".png")
        return os.path.join(base, a["id"] + ".png")

    def _show_preview(self, aid):
        a = self._asset_by_id(aid)
        path = self._out_path_for(a) if a else os.path.join(self.vars["out_dir"].get(), aid + ".png")
        if not os.path.exists(path):
            path = os.path.join(self.vars["out_dir"].get(), aid + ".png")
        if not os.path.exists(path):
            self.preview.config(image="", text=t("(jeszcze nie wygenerowano)"))
            self._preview_img = None
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((360, 360))
            self._preview_img = ImageTk.PhotoImage(img)
            self.preview.config(image=self._preview_img, text="")
        except Exception as e:
            self.preview.config(image="", text=t("(podglad: {e})", e=e))
            self._preview_img = None

    def _start(self, missing_only):
        if self.worker and self.worker.is_alive():
            return
        for k, v in self.vars.items():
            self.cfg[k] = v.get()
        mode = self.mode_var.get()
        if mode == "local":
            # sprawdz klienta uslugi Qwen zanim cokolwiek odpalimy
            client_py = os.path.join(self.cfg["qwen_dir"], "ubnt_qwen_client.py")
            if not os.path.exists(client_py):
                messagebox.showerror(t("Brak pliku"), t("Nie znaleziono klienta Qwen 2.1:\n{plik}\n\nWskaz wlasciwy folder przyciskiem ...", plik=client_py))
                return
        else:
            if not self.apikey_var.get().strip():
                messagebox.showerror(t("Brak klucza API"),
                                      t("Wpisz klucz API (Google AI Studio) w polu 'Klucz API' powyzej."))
                return
        out_dir = self.cfg["out_dir"]
        if missing_only:
            def _done(a):
                return os.path.exists(os.path.join(out_dir, a["id"] + ".png")) or \
                    (a.get("category") and os.path.exists(os.path.join(out_dir, str(a["category"]), a["id"] + ".png")))
            jobs = [a for a in self.assets if not _done(a)]
        else:
            jobs = [self._asset_by_id(i) for i in self.tree.selection()]
            jobs = [j for j in jobs if j]
        if not jobs:
            self._log(t("Nic do zrobienia."))
            return
        self.stop_flag.clear()
        self.btn_sel.config(state="disabled")
        self.btn_all.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.worker = threading.Thread(target=self._run_jobs, args=(jobs,), daemon=True)
        self.worker.start()

    def _ensure_model(self):
        """Uruchamia usluge Qwen 2.1 (jesli nie dziala) i czeka az model sie zaladuje."""
        qwen21.QWEN_DIR = self.cfg["qwen_dir"]
        c = qwen21.client()
        self.msg_q.put(("log", t("Usluga Qwen-Image-2.1 ({url}) - sprawdzam / uruchamiam (start do kilku minut)...", url=c.URL)))
        c.ensure_running()
        self.msg_q.put(("log", t("Usluga Qwen gotowa.")))

    def _ensure_api_client(self):
        if self._genai_client is not None:
            return
        api_key = self.apikey_var.get().strip()
        if not api_key:
            raise RuntimeError(t("Brak klucza API."))
        from google import genai  # pip install google-genai
        self._genai_client = genai.Client(api_key=api_key)
        self.msg_q.put(("log", t("Polaczono z Google AI Studio API.")))

    def _generate_via_api(self, prompt, negative, w, h, przezroczyste=False):
        """Generuje jeden obraz przez Google AI Studio (Gemini image models). Zwraca PIL.Image RGBA.
        Wymog jednolitej zieleni dopisujemy TYLKO grafikom z przezroczystym tlem - slowo 'green'
        w opisie tla poziomu (np. 'green grass') nie moze zamienic go w zielony ekran."""
        from google.genai import types
        from PIL import Image
        from io import BytesIO

        full_prompt = prompt
        if przezroczyste and ("green" in prompt.lower() or "chroma" in prompt.lower()):
            full_prompt += ("\n\nBackground requirement: the ENTIRE background is one completely flat, "
                            "uniform, untextured field of a single solid color (bright pure green), "
                            "like a studio chroma-key screen - no patterns, no brush texture, no noise, "
                            "no gradients, no shadows cast on the background.")
        if negative and negative.strip():
            full_prompt = f"{full_prompt}\n\nUnikaj w obrazie: {negative}"

        config_kwargs = {"response_modalities": ["TEXT", "IMAGE"]}
        try:
            config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=nearest_aspect_ratio(w, h))
        except Exception:
            pass  # starsza wersja SDK bez ImageConfig - jedziemy bez wymuszania proporcji

        model = self.apimodel_var.get().strip() or "gemini-2.5-flash-image"
        response = self._genai_client.models.generate_content(
            model=model, contents=full_prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        cand = response.candidates[0] if response.candidates else None
        if cand and cand.content and cand.content.parts:
            for part in cand.content.parts:
                if getattr(part, "inline_data", None) is not None:
                    return Image.open(BytesIO(part.inline_data.data)).convert("RGBA")
        raise RuntimeError(t("API nie zwrocilo obrazu (sprawdz klucz / limit zapytan / tresc prompta)."))

    def _run_jobs(self, jobs):
        out_dir = self.cfg["out_dir"]
        raw_dir = os.path.join(out_dir, "_raw")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(raw_dir, exist_ok=True)
        mode = self.mode_var.get()
        if mode == "local":
            try:
                self._ensure_model()
            except ImportError as e:
                self.msg_q.put(("log", t("BLAD: {e}", e=e)))
                self.msg_q.put(("done", None)); return
            except Exception as e:
                self.msg_q.put(("log", t("BLAD ladowania modelu: {e}", e=e)))
                self.msg_q.put(("done", None)); return
        else:
            try:
                self._ensure_api_client()
            except ImportError:
                self.msg_q.put(("log", t("BLAD: brak biblioteki 'google-genai'. Zainstaluj w tym samym venv: pip install google-genai")))
                self.msg_q.put(("done", None)); return
            except Exception as e:
                self.msg_q.put(("log", t("BLAD polaczenia z API: {e}", e=e)))
                self.msg_q.put(("done", None)); return

        total = len(jobs)
        steps = int(self.steps_var.get())
        seed_txt = self.seed_var.get().strip()
        api_delay = 0.0
        if mode == "api":
            try:
                api_delay = float(self.apidelay_var.get().strip() or 0)
            except ValueError:
                api_delay = 0.0

        for i, a in enumerate(jobs, 1):
            if self.stop_flag.is_set():
                self.msg_q.put(("log", t("Zatrzymano."))); break
            aid = a["id"]
            self.msg_q.put(("status", aid, t("generuje...")))
            w, h = asset_dims(a)
            neg = (a.get("negative") or "").strip() or (self.negative or "").strip() \
                or str(self.cfg.get("default_negative", ""))

            if mode == "local":
                def cb(txt, _aid=aid, _i=i):
                    self.msg_q.put(("progress", f"{_i}/{total} {_aid} | {jezyk.postep(txt)}"))

                self.msg_q.put(("progress", f"{i}/{total} {aid} | " + t("wysylanie do Qwen 2.1...")))
                base_seed = None
                if seed_txt:
                    try:
                        base_seed = int(seed_txt)
                    except ValueError:
                        base_seed = None
                eff_seed = group_seed(base_seed, a, self.group_var.get().strip())
                try:
                    img, res = qwen21.generate(tlo.sanitize_prompt(a["prompt"]), neg, w, h, steps,
                                               seed=eff_seed, progress_cb=cb)
                    out = [img]
                    self.msg_q.put(("log", f"{aid}: {res['width']}x{res['height']} -> {w}x{h}, "
                                           f"seed {res['seed']}, {res['seconds']} s"))
                except Exception as e:
                    self.msg_q.put(("log", f"[err] {aid}: {e}"))
                    self.msg_q.put(("status", aid, t("BLAD"))); continue
            else:
                self.msg_q.put(("progress", f"{i}/{total} {aid} | " + t("wysylanie do API...")))
                try:
                    img = self._generate_via_api(tlo.sanitize_prompt(a["prompt"]), neg, w, h,
                                                 przezroczyste=self._przezroczyste(a))
                except Exception as e:
                    self.msg_q.put(("log", f"[err] {aid}: {e}"))
                    self.msg_q.put(("status", aid, t("BLAD"))); continue
                out = [img]
                if api_delay > 0:
                    time.sleep(api_delay)

            raw_path = os.path.join(raw_dir, aid + ".png")
            dst_dir = out_dir
            if self.subdir_var.get() and a.get("category"):
                dst_dir = os.path.join(out_dir, str(a["category"]))
                os.makedirs(dst_dir, exist_ok=True)
            out_path = os.path.join(dst_dir, aid + ".png")
            try:
                out[0].save(raw_path)
                if self._przezroczyste(a):
                    # API (Gemini) nie oddaje jednolitej zieleni -> najpierw rembg (segmentacja),
                    # lokalny Qwen oddaje czysta zielen -> najpierw szybki chroma key (patrz tlo.py)
                    order = ("rembg", "chroma") if mode != "local" else ("chroma", "rembg")
                    used = tlo.wytnij_tlo(raw_path, out_path, order, chroma=self.chroma_var.get(),
                                          rembg=self.rembg_var.get(),
                                          log=lambda t, _aid=aid: self.msg_q.put(("log", f"{_aid}: {t}")))
                    if used:
                        self.msg_q.put(("log", f"{aid}: " + t("tlo wyciete ({narzedzie})", narzedzie=used)))
                else:
                    out[0].save(out_path)
                self.msg_q.put(("status", aid, t("zrobione")))
                self.msg_q.put(("preview", aid))
            except Exception as e:
                self.msg_q.put(("log", f"[post] {aid}: {e}"))
                self.msg_q.put(("status", aid, t("BLAD")))
        self.msg_q.put(("done", None))

    @staticmethod
    def _przezroczyste(a):
        return "transparent" in str(a.get("background", "")).lower()

    def _stop(self):
        self.stop_flag.set()
        self._log(t("Zatrzymanie po biezacym obrazku..."))

    def _poll_queue(self):
        try:
            while True:
                kind, *rest = self.msg_q.get_nowait()
                if kind == "log":
                    self._log(rest[0])
                elif kind == "status":
                    aid, status = rest
                    if self.tree.exists(aid):
                        a = self._asset_by_id(aid)
                        self.tree.item(aid, values=(aid, a.get("category", ""), status))
                elif kind == "preview":
                    self._show_preview(rest[0])
                elif kind == "progress":
                    self.progress.config(text=rest[0])
                elif kind == "done":
                    self.progress.config(text=t("Gotowe."))
                    self.btn_sel.config(state="normal")
                    self.btn_all.config(state="normal")
                    self.btn_stop.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _log(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")


if __name__ == "__main__":
    App().mainloop()
