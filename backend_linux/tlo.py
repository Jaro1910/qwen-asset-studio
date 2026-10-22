#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# tlo.py - wspolne wycinanie tla dla Pan Kret Studio, generuj.py i edycji.
# Jedna funkcja dla wszystkich programow: ten sam prompt daje ten sam wynik w GUI i bez okna.
#
# Kolejnosc narzedzi:
#   - lokalny Qwen oddaje czysta zielen -> najpierw chroma key, rembg ratunkiem,
#   - API (Gemini) nie oddaje jednolitej zieleni -> najpierw rembg, chroma key ratunkiem.
# Chroma key liczy sie jako NIEUDANY, gdy wytnie mniej niz MIN_WYCIETE obrazka - wtedy tlo
# nie bylo zielone (np. prompt nie prosil o #00FF00) i wycinanie przejmuje rembg.
# Chroma key uzywa tych samych dwoch kluczy zieleni co Studio sprzed tlo.py, a dodatkowo maski: zielen
# otoczona obiektem zostaje (patrz chroma_cut).

import os
import shutil

from jezyk import t

# Ponizej tej czesci obrazka wycietej przez chroma key uznajemy, ze tlo nie bylo zielone.
MIN_WYCIETE = 0.05

# Szerokosc miekkiej krawedzi maski w px. Wieksza rozmywa sprite'y i gubi cienkie detale (sprawdzone
# na 5-14 px), 2 px daje czyste krawedzie.
KRAWEDZ_PX = 2

_sesja_rembg = None   # model rembg wczytany raz na proces (ok. 1 GB) - nie przy kazdym obrazku


def sanitize_prompt(p):
    """Qwen-Image potrafi NAMALOWAC doslowne kody/napisy z prompta - '#00FF00' laduje
    jako tekst na obrazku. Zamieniamy kod na opis slowny."""
    return p.replace("#00FF00", "solid uniform pure green chroma-key")


def chroma_cut(src, dst):
    """Wycina zielone tlo maska: kontur obiektu, wypelnione wnetrze, krawedz rozmyta o KRAWEDZ_PX.
    Zwraca, jaka czesc obrazka zajmuje zielen tla (0.0-1.0) - do decyzji, czy tlo bylo zielone.
    Zielen otoczona obiektem zostaje (np. zielony pasek w ramce), dziura w kolorze tla jest
    przezroczysta (np. srodek litery). Zielen wystajaca poza sylwetke obiektu jest wycinana."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage   # instaluje sie razem z rembg
    arr = np.asarray(Image.open(src).convert("RGB")).astype(np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # klucz 1: czysta/mocna zielen
    green = (g > 100) & (g > r + 40) & (g > b + 40)
    # klucz 2: kolor tla z ramki (mediana 8px brzegu) + tolerancja - lapie zielen przybrudzona
    # albo turkusowa (Qwen tak maluje tlo, gdy obiekt sam jest zielony). Tylko gdy ramka jest
    # zielonkawa: na czarnym czy bialym tle wycialby kawalki obiektu w tym kolorze (wtedy rembg).
    edge = np.concatenate([arr[:8].reshape(-1, 3), arr[-8:].reshape(-1, 3),
                           arr[:, :8].reshape(-1, 3), arr[:, -8:].reshape(-1, 3)])
    bg = np.median(edge, axis=0)
    zielonkawe = bg[1] > 150 and bg[1] > bg[0] + 60 and bg[1] > bg[2]
    if zielonkawe:
        green = green | (np.abs(arr - bg).sum(axis=2) < 60)
    obiekt = ~green
    # dziury = zielone obszary niepolaczone z brzegiem obrazka; inna zielen niz tlo = czesc obiektu
    etyk, n = ndimage.label(green)
    przy_brzegu = set(np.unique(np.concatenate([etyk[0], etyk[-1], etyk[:, 0], etyk[:, -1]]))) - {0}
    for i, sl in enumerate(ndimage.find_objects(etyk), 1):   # kazda dziura tylko w swoim prostokacie
        if sl is None or i in przy_brzegu:
            continue
        dziura = etyk[sl] == i
        if np.abs(np.median(arr[sl][dziura], axis=0) - bg).sum() > 60:
            obiekt[sl] |= dziura
    # miekka krawedz do SRODKA obiektu (zwezenie, potem rozmycie) - bez zielonej obwodki
    a = ndimage.binary_erosion(obiekt, iterations=max(1, KRAWEDZ_PX // 2)).astype(np.float32)
    a = np.minimum(ndimage.gaussian_filter(a, sigma=KRAWEDZ_PX / 2), obiekt.astype(np.float32))
    alpha = (a * 255).clip(0, 255).astype(np.uint8)
    # despill: zbij zielony nalot tla na obiekcie, ale nie ruszaj zieleni obiektu (daleko od koloru tla)
    if zielonkawe:
        spill = obiekt & (g > np.maximum(r, b)) & ~(np.abs(arr - bg).sum(axis=2) > 200)
        arr[..., 1] = np.where(spill, np.maximum(r, b), g)
    Image.fromarray(np.dstack([arr.clip(0, 255).astype(np.uint8), alpha]), "RGBA").save(dst)
    return float(green.mean())


def rembg_cut(src, dst, log=print):
    """Wycina tlo segmentacja (rembg) - dziala na dowolnym tle."""
    global _sesja_rembg
    from rembg import new_session, remove
    from PIL import Image
    if _sesja_rembg is None:
        log(t("[rembg] laduje model wycinania - przy pierwszym uzyciu na tym komputerze pobiera go "
              "z internetu (ok. 1 GB, kilka minut, postep widac w terminalu)"))
        _sesja_rembg = new_session()
        log(t("[rembg] model gotowy"))
    remove(Image.open(src).convert("RGBA"), session=_sesja_rembg).save(dst)


def wytnij_tlo(src, dst, kolejnosc=("chroma", "rembg"), chroma=True, rembg=True, log=print):
    """Wycina tlo z src do dst. Zwraca nazwe uzytego narzedzia albo None, gdy zadne sie
    nie udalo - wtedy dst to kopia src (z tlem) i log dostaje ostrzezenie.
    Kazde narzedzie pisze do pliku tymczasowego, a dst powstaje dopiero z gotowego wyniku:
    przerwana praca nie zostawia w folderze wynikow pliku, ktory 'Generuj brakujace' uznalby za gotowy."""
    wlaczone = {"chroma": chroma, "rembg": rembg}
    tmp = dst + ".tmp.png"
    try:
        for narzedzie in kolejnosc:
            if not wlaczone.get(narzedzie):
                continue
            try:
                if narzedzie == "chroma":
                    wyciete = chroma_cut(src, tmp)
                    if wyciete < MIN_WYCIETE:
                        log(t("[chroma] wyciete tylko {ile} obrazka - tlo nie jest zielone", ile=f"{wyciete:.1%}"))
                        continue
                else:
                    rembg_cut(src, tmp, log)
                os.replace(tmp, dst)
                return narzedzie
            except Exception as e:
                log(t("[{narzedzie} nie wypalil] {e}", narzedzie=narzedzie, e=e))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    shutil.copyfile(src, dst)
    log(t("UWAGA: tlo NIE zostalo wyciete - zapisano obrazek z tlem"))
    return None
