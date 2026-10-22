#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# edit_backend.py (LINUX) - uniwersalny backend edycji obrazow przez Qwen-Image-2.1
#
# Idea: bierze obrazy zrodlowe z folderu, sprawdza w manifescie (edits.json) jakie
# prompty sa do nich przypisane, i dla KAZDEGO promptu generuje wariant z tym obrazem
# jako referencja (endpoint /edit uslugi Qwen 2.1, patrz qwen21.py).
# Na Windowsie praca szla na oba GPU (proces na karte); tu model na obu kartach trzyma
# usluga i robi jedno zadanie naraz, wiec backend leci po kolei w jednym procesie.
#
# Uruchom:  python edit_backend.py --manifest ../edits.json
#   --dry-run              : tylko wypisz, co jest do zrobienia
#   --src-dir / --out-dir  : nadpisz foldery z manifestu (np. manifest z Windowsa)
#   --gpus                 : ignorowane (zgodnosc z wersja windowsowa)

import argparse, json, os, sys

import qwen21
import tlo
from jezyk import t, postep


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_tasks(m):
    """Deterministyczna, uporzadkowana lista zadan: (source_path, out_path, prompt, w, h, transparent)."""
    src_dir = m["src_dir"]
    out_dir = m["out_dir"]
    tasks = []
    for job in m["jobs"]:
        src = os.path.join(src_dir, job["source"])
        w, h = job.get("size", [512, 512])
        transp = bool(job.get("transparent", False))
        for o in job["outputs"]:
            ow, oh = o.get("size", [w, h])
            out = os.path.join(out_dir, o["id"] + ".png")
            tasks.append((src, out, o["prompt"], ow, oh, transp))
    return tasks


def run(args):
    m = load_manifest(args.manifest)
    if args.src_dir:
        m["src_dir"] = args.src_dir
    if args.out_dir:
        m["out_dir"] = args.out_dir
    # sciezki wzgledne w manifescie liczone od folderu manifestu
    base = os.path.dirname(os.path.abspath(args.manifest))
    for k in ("src_dir", "out_dir"):
        m[k] = os.path.join(base, os.path.expanduser(m[k]))
    tasks = build_tasks(m)
    todo = [z for z in tasks if not os.path.exists(z[1])]
    print(t("Zadan w manifescie: {n}, do zrobienia: {m}", n=len(tasks), m=len(todo)), flush=True)

    if args.dry_run:
        for i, z in enumerate(tasks):
            mark = "OK" if os.path.exists(z[1]) else "-> Qwen 2.1"
            print(f"  [{i}] {os.path.splitext(os.path.basename(z[1]))[0]:<22} {mark}  ref={os.path.basename(z[0])}")
        return 0
    if not todo:
        return 0

    os.makedirs(m["out_dir"], exist_ok=True)
    if m.get("qwen_dir"):
        qwen21.QWEN_DIR = m["qwen_dir"]
    c = qwen21.client()
    print(t("usluga Qwen 2.1 ({url}) - sprawdzam / uruchamiam...", url=c.URL), flush=True)
    c.ensure_running()
    print(t("usluga gotowa."), flush=True)

    steps = int(m.get("steps", 20))
    for n, (src, out, prompt, w, h, transp) in enumerate(tasks, 1):
        oid = os.path.splitext(os.path.basename(out))[0]
        if os.path.exists(out):
            print(f"[{n}/{len(tasks)}] {oid} - " + t("pomijam (jest)"), flush=True)
            continue
        if not os.path.exists(src):
            print(f"[{n}/{len(tasks)}] {oid} - " + t("BRAK ZRODLA {plik}", plik=src), flush=True)
            continue
        print(f"[{n}/{len(tasks)}] {oid} <- {os.path.basename(src)} ({w}x{h})", flush=True)

        def cb(txt, _oid=oid):
            print(f"  {_oid}: {postep(txt)}", flush=True)

        try:
            img, _ = qwen21.edit(src, tlo.sanitize_prompt(prompt), w, h, steps, progress_cb=cb)
        except Exception as e:
            print(f"[err] {oid}: {e}", flush=True)
            continue
        if transp:
            # edycja wycina tlo samym rembg (zrodla nie musza byc na zieleni); nieudane wycinanie
            # zapisuje obrazek z tlem i wypisuje ostrzezenie (tlo.py)
            raw = os.path.join(m["out_dir"], "_raw_" + oid + ".png")
            img.save(raw)
            tlo.wytnij_tlo(raw, out, ("rembg",), log=lambda tekst, _oid=oid: print(f"  {_oid}: {tekst}", flush=True))
            try: os.remove(raw)
            except OSError: pass
        else:
            img.save(out)
        print(f"[{n}/{len(tasks)}] {oid} -> " + t("zapisano"), flush=True)

    print("\n" + t("Koniec."), flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Uniwersalny backend edycji obrazow (Qwen-Image-2.1)")
    ap.add_argument("--manifest", default="edits.json")
    ap.add_argument("--src-dir", default=None, help="nadpisuje src_dir z manifestu")
    ap.add_argument("--out-dir", default=None, help="nadpisuje out_dir z manifestu")
    ap.add_argument("--gpus", default=None, help=argparse.SUPPRESS)   # ignorowane - GPU obsluguje usluga
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
