#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Pan Kret Edit Studio (LINUX) - GUI do edycji obrazow przez Qwen-Image-2.1.
# Wybierasz foldery przez pickery, klikasz zrodlo, dopisujesz mu prompty w oknie,
# klikasz Generuj. Manifest (edits.json) zapisuje sie sam. Generacje odpala edit_backend.py,
# ktory wysyla zadania do uslugi Qwen 2.1 (ona trzyma model na obu GPU). Uruchom: ./run_edit_ui.sh

import json, os, queue, signal, subprocess, sys, threading, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import qwen21
import jezyk
from jezyk import t

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)
CONFIG_PATH = os.path.join(APP_DIR, "config_edit.json")
BACKEND = os.path.join(APP_DIR, "edit_backend.py")

DEFAULT_CFG = {
    "qwen_dir": qwen21.QWEN_DIR,
    "src_dir": os.path.expanduser("~/backends/refs/pan-kret-studio"),
    "out_dir": os.path.expanduser("~/backends/output/pan-kret-studio"),
    "manifest": os.path.join(REPO_DIR, "edits.json"),
    "steps": 20, "size": "512", "transparent": True,
}
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def parse_size(s):
    s = str(s).lower().replace(" ", "")
    if "x" in s:
        a, b = s.split("x")[:2]
        return [int(a), int(b)]
    n = int(s)
    return [n, n]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pan Kret Edit Studio")
        self.geometry("1180x760")
        self.cfg = self._load_cfg()
        self.jobs_by_src = {}      # nazwa_pliku -> {source,size,transparent,outputs:[{id,prompt}]}
        self.current_src = None
        self.proc = None
        self.msg_q = queue.Queue()
        self._preview_img = None
        self._build_ui()
        self._load_manifest()
        self._refresh_sources()
        self.after(150, self._poll)

    # ---------- config / manifest ----------
    def _load_cfg(self):
        c = dict(DEFAULT_CFG)
        if os.path.exists(CONFIG_PATH):
            try: c.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
            except Exception: pass
        return c

    def _pola_do_cfg(self):
        """Przepisuje pola okna do self.cfg (bez zapisu na dysk)."""
        for k, v in self.vars.items():
            self.cfg[k] = v.get()
        self.cfg["steps"] = int(self.steps_var.get())
        self.cfg["size"] = self.size_var.get().strip()
        self.cfg["transparent"] = bool(self.transp_var.get())

    def _save_cfg(self):
        self._pola_do_cfg()
        json.dump(self.cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        self._log(t("Zapisano ustawienia."))

    def _przelacz_jezyk(self):
        """PL <-> EN od razu: okno budowane od nowa, pola, zrodla, prompty i log zostaja."""
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo(t("Trwa generowanie"), t("Jezyk zmienisz po zakonczeniu generowania."))
            return
        self._capture_source_fields()
        self._pola_do_cfg()
        log = self.log.get("1.0", "end-1c")
        jezyk.ustaw("en" if jezyk.kod() == "pl" else "pl")
        for w in self.winfo_children():
            w.destroy()
        self.current_src = None
        self._build_ui()
        self._refresh_sources()
        self.log.delete("1.0", "end")
        self.log.insert("1.0", log + "\n")
        self.log.see("end")

    def _load_manifest(self):
        path = self.vars["manifest"].get()
        self.jobs_by_src = {}
        if os.path.exists(path):
            try:
                m = json.load(open(path, encoding="utf-8"))
                for j in m.get("jobs", []):
                    self.jobs_by_src[j["source"]] = j
            except Exception as e:
                self._log(t("Nie wczytano manifestu: {e}", e=e))

    def _build_manifest(self):
        self._capture_source_fields()
        jobs = [j for j in self.jobs_by_src.values() if j.get("outputs")]
        return {
            "src_dir": self.vars["src_dir"].get(), "out_dir": self.vars["out_dir"].get(),
            "qwen_dir": self.vars["qwen_dir"].get(),
            "steps": int(self.steps_var.get()),
            "jobs": jobs,
        }

    def _save_manifest(self):
        m = self._build_manifest()
        json.dump(m, open(self.vars["manifest"].get(), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return m

    # ---------- UI ----------
    def _build_ui(self):
        bar = ttk.Frame(self); bar.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Button(bar, text=t("Jezyk: PL"), command=self._przelacz_jezyk).pack(side="right")
        top = ttk.LabelFrame(self, text=t("Ustawienia"))
        top.pack(fill="x", padx=8, pady=6)
        self.vars = {}
        rows = [("qwen_dir", "Qwen-Image-2.1", "dir"), ("src_dir", "Folder zrodel (refs)", "dir"),
                ("out_dir", "Folder wyjsciowy", "dir"), ("manifest", "Manifest (.json)", "file")]
        for i, (key, label, br) in enumerate(rows):
            ttk.Label(top, text=t(label), width=24).grid(row=i, column=0, sticky="w", padx=4, pady=1)
            v = tk.StringVar(value=str(self.cfg.get(key, "")))
            self.vars[key] = v
            ttk.Entry(top, textvariable=v, width=86).grid(row=i, column=1, sticky="we", padx=4)
            ttk.Button(top, text="...", width=3, command=lambda k=key, b=br: self._browse(k, b)).grid(row=i, column=2, padx=4)
        top.columnconfigure(1, weight=1)
        opts = ttk.Frame(top); opts.grid(row=len(rows), column=0, columnspan=3, sticky="w", padx=4, pady=4)
        self.steps_var = tk.IntVar(value=int(self.cfg.get("steps", 20)))
        ttk.Label(opts, text=t("Kroki:")).pack(side="left"); ttk.Spinbox(opts, from_=4, to=60, width=5, textvariable=self.steps_var).pack(side="left", padx=(2, 10))
        ttk.Label(opts, text=t("Rozmiar (np. 512 lub 512x288):")).pack(side="left"); self.size_var = tk.StringVar(value=str(self.cfg.get("size", "512")))
        ttk.Entry(opts, textvariable=self.size_var, width=10).pack(side="left", padx=(2, 10))
        ttk.Button(opts, text=t("Zapisz ustawienia"), command=self._save_cfg).pack(side="left", padx=8)
        ttk.Button(opts, text=t("Odswiez zrodla"), command=self._refresh_sources).pack(side="left")

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=8, pady=4)

        # zrodla
        lf = ttk.LabelFrame(mid, text=t("Zrodla (z folderu refs)")); lf.pack(side="left", fill="both", expand=True)
        self.src_tree = ttk.Treeview(lf, columns=("plik", "prompty"), show="headings", selectmode="browse")
        self.src_tree.heading("plik", text=t("plik")); self.src_tree.column("plik", width=200)
        self.src_tree.heading("prompty", text=t("prompty")); self.src_tree.column("prompty", width=70, anchor="center")
        self.src_tree.pack(fill="both", expand=True, side="left")
        self.src_tree.bind("<<TreeviewSelect>>", self._on_src_select)
        ttk.Scrollbar(lf, orient="vertical", command=self.src_tree.yview).pack(side="left", fill="y")

        # prompty zrodla
        mf = ttk.LabelFrame(mid, text=t("Prompty wybranego zrodla")); mf.pack(side="left", fill="both", expand=True, padx=8)
        self.out_tree = ttk.Treeview(mf, columns=("id", "prompt"), show="headings", selectmode="browse", height=8)
        self.out_tree.heading("id", text=t("id (nazwa pliku wynikowego)")); self.out_tree.column("id", width=180)
        self.out_tree.heading("prompt", text="prompt"); self.out_tree.column("prompt", width=320)
        self.out_tree.pack(fill="both", expand=True)
        self.out_tree.bind("<<TreeviewSelect>>", self._on_out_select)
        srow = ttk.Frame(mf); srow.pack(fill="x", pady=2)
        self.transp_var = tk.BooleanVar(value=bool(self.cfg.get("transparent", True)))
        ttk.Checkbutton(srow, text=t("Przezroczyste (odetnij tlo)"), variable=self.transp_var).pack(side="left")
        ttk.Label(srow, text=t("Rozmiar zrodla:")).pack(side="left", padx=(10, 2))
        self.srcsize_var = tk.StringVar(value="")
        ttk.Entry(srow, textvariable=self.srcsize_var, width=10).pack(side="left")
        ttk.Label(mf, text=t("id wyniku:")).pack(anchor="w")
        self.oid_var = tk.StringVar()
        ttk.Entry(mf, textvariable=self.oid_var).pack(fill="x")
        ttk.Label(mf, text=t("prompt (instrukcja edycji):")).pack(anchor="w")
        self.prompt_txt = tk.Text(mf, height=5, wrap="word"); self.prompt_txt.pack(fill="x")
        brow = ttk.Frame(mf); brow.pack(fill="x", pady=3)
        ttk.Button(brow, text=t("Dodaj / zmien prompt"), command=self._add_output).pack(side="left")
        ttk.Button(brow, text=t("Usun prompt"), command=self._remove_output).pack(side="left", padx=6)

        # podglad
        rf = ttk.LabelFrame(mid, text=t("Podglad ostatniego wyniku")); rf.pack(side="left", fill="both")
        self.preview = ttk.Label(rf, text=t("(brak)"), width=42, anchor="center"); self.preview.pack(fill="both", expand=True, padx=6, pady=6)

        bottom = ttk.Frame(self); bottom.pack(fill="both", padx=8, pady=6)
        b = ttk.Frame(bottom); b.pack(fill="x")
        self.btn_all = ttk.Button(b, text=t("Generuj wszystko"), command=lambda: self._generate(False)); self.btn_all.pack(side="left")
        self.btn_sel = ttk.Button(b, text=t("Generuj wybrane zrodlo"), command=lambda: self._generate(True)); self.btn_sel.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(b, text=t("Stop"), command=self._stop, state="disabled"); self.btn_stop.pack(side="left")
        self.progress = ttk.Label(b, text=""); self.progress.pack(side="right")
        self.log = tk.Text(bottom, height=9, wrap="word", bg="#101010", fg="#d0d0d0"); self.log.pack(fill="both", expand=True, pady=(6, 0))

    def _browse(self, key, kind):
        p = filedialog.askdirectory() if kind == "dir" else filedialog.askopenfilename()
        if p:
            self.vars[key].set(p)
            if key == "manifest":
                self._load_manifest(); self._refresh_sources()
            if key == "src_dir":
                self._refresh_sources()

    # ---------- zrodla / outputs ----------
    def _refresh_sources(self):
        self._capture_source_fields()
        self.src_tree.delete(*self.src_tree.get_children())
        d = self.vars["src_dir"].get()
        files = []
        if os.path.isdir(d):
            files = sorted(f for f in os.listdir(d) if f.lower().endswith(IMG_EXT))
        for f in files:
            n = len(self.jobs_by_src.get(f, {}).get("outputs", []))
            self.src_tree.insert("", "end", iid=f, values=(f, n))
        self._log(t("Zrodel: {n} w {folder}", n=len(files), folder=d))

    def _job(self, src):
        if src not in self.jobs_by_src:
            self.jobs_by_src[src] = {"source": src, "size": parse_size(self.size_var.get()),
                                     "transparent": bool(self.transp_var.get()), "outputs": []}
        return self.jobs_by_src[src]

    def _capture_source_fields(self):
        if not self.current_src:
            return
        j = self.jobs_by_src.get(self.current_src)
        if not j:
            return
        j["transparent"] = bool(self.transp_var.get())
        try: j["size"] = parse_size(self.srcsize_var.get() or self.size_var.get())
        except ValueError: pass

    def _on_src_select(self, _e):
        self._capture_source_fields()
        sel = self.src_tree.selection()
        if not sel:
            return
        self.current_src = sel[0]
        j = self._job(self.current_src)
        self.transp_var.set(bool(j.get("transparent", True)))
        sz = j.get("size", parse_size(self.size_var.get()))
        self.srcsize_var.set(f"{sz[0]}x{sz[1]}")
        self._fill_outputs(j)

    def _fill_outputs(self, j):
        self.out_tree.delete(*self.out_tree.get_children())
        for o in j.get("outputs", []):
            self.out_tree.insert("", "end", iid=o["id"], values=(o["id"], o["prompt"][:90]))

    def _on_out_select(self, _e):
        sel = self.out_tree.selection()
        if not sel or not self.current_src:
            return
        for o in self.jobs_by_src[self.current_src]["outputs"]:
            if o["id"] == sel[0]:
                self.oid_var.set(o["id"])
                self.prompt_txt.delete("1.0", "end"); self.prompt_txt.insert("1.0", o["prompt"])
                break

    def _add_output(self):
        if not self.current_src:
            messagebox.showinfo(t("Wybierz zrodlo"), t("Najpierw kliknij zrodlo na liscie po lewej.")); return
        oid = self.oid_var.get().strip()
        prompt = self.prompt_txt.get("1.0", "end").strip()
        if not oid or not prompt:
            messagebox.showinfo(t("Brak danych"), t("Podaj id wyniku i prompt.")); return
        j = self._job(self.current_src)
        for o in j["outputs"]:
            if o["id"] == oid:
                o["prompt"] = prompt; break
        else:
            j["outputs"].append({"id": oid, "prompt": prompt})
        self._capture_source_fields()
        self._fill_outputs(j)
        self.src_tree.item(self.current_src, values=(self.current_src, len(j["outputs"])))
        self._save_manifest()
        self._log(t("Zapisano prompt '{id}' dla {zrodlo}", id=oid, zrodlo=self.current_src))

    def _remove_output(self):
        sel = self.out_tree.selection()
        if not sel or not self.current_src:
            return
        j = self.jobs_by_src[self.current_src]
        j["outputs"] = [o for o in j["outputs"] if o["id"] != sel[0]]
        self._fill_outputs(j)
        self.src_tree.item(self.current_src, values=(self.current_src, len(j["outputs"])))
        self._save_manifest()

    # ---------- generowanie ----------
    def _generate(self, selected_only):
        if self.proc and self.proc.poll() is None:
            return
        self._save_cfg()
        m = self._save_manifest()
        if selected_only:
            if not self.current_src or not self.jobs_by_src.get(self.current_src, {}).get("outputs"):
                messagebox.showinfo(t("Nic do zrobienia"), t("Wybierz zrodlo z przypisanymi promptami.")); return
            m = dict(m); m["jobs"] = [self.jobs_by_src[self.current_src]]
            man_path = os.path.join(APP_DIR, "_edits_selected.json")
            json.dump(m, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        else:
            man_path = self.vars["manifest"].get()
            if not m["jobs"]:
                messagebox.showinfo(t("Pusto"), t("Brak zrodel z promptami.")); return

        cmd = [sys.executable, "-u", BACKEND, "--manifest", man_path]
        self._log("> " + " ".join(cmd))
        self.btn_all.config(state="disabled"); self.btn_sel.config(state="disabled"); self.btn_stop.config(state="normal")
        try:
            # wlasna grupa procesow -> Stop zabija backend; usluga Qwen ma swoja sesje i zyje dalej
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace",
                                         cwd=APP_DIR, start_new_session=True,
                                         env=dict(os.environ, PKS_JEZYK=jezyk.kod()))
        except Exception as e:
            self._log(t("[err] nie udalo sie uruchomic: {e}", e=e)); self._reset_buttons(); return
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            self.msg_q.put(("log", line.rstrip()))
        self.proc.wait()
        self.msg_q.put(("done", None))

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except Exception as e:
                self._log(f"[stop] {e}")
        self._log(t("Zatrzymywanie..."))

    def _reset_buttons(self):
        self.btn_all.config(state="normal"); self.btn_sel.config(state="normal"); self.btn_stop.config(state="disabled")

    # ---------- podglad / petla ----------
    def _newest_output(self):
        d = self.vars["out_dir"].get()
        ids = []
        for j in self.jobs_by_src.values():
            ids += [o["id"] for o in j.get("outputs", [])]
        best = None; bt = -1
        for i in ids:
            p = os.path.join(d, i + ".png")
            if os.path.exists(p):
                t = os.path.getmtime(p)
                if t > bt:
                    bt = t; best = p
        return best

    def _show_preview(self, path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path); img.thumbnail((340, 340))
            self._preview_img = ImageTk.PhotoImage(img)
            self.preview.config(image=self._preview_img, text="")
        except Exception:
            pass

    def _poll(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == "log":
                    self._log(payload); self.progress.config(text=payload[-60:])
                elif kind == "done":
                    self._reset_buttons(); self.progress.config(text=t("Gotowe."))
                    p = self._newest_output()
                    if p: self._show_preview(p)
        except queue.Empty:
            pass
        if self.proc and self.proc.poll() is None:
            p = self._newest_output()
            if p: self._show_preview(p)
        self.after(800, self._poll)

    def _log(self, t):
        self.log.insert("end", t + "\n"); self.log.see("end")


if __name__ == "__main__":
    App().mainloop()
