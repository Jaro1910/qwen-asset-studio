#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# jezyk.py - jezyk interfejsu (PL / EN) dla Studio, Edit Studio, generuj.py i edit_backend.py.
# Teksty w kodzie sa po polsku; t("tekst") zwraca tlumaczenie, gdy wybrany jest angielski.
# Wybor trzyma jezyk.json obok tego pliku (wspolny dla wszystkich programow). Domyslnie: angielski.

import json
import os
import re

_PLIK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jezyk.json")
_kod = "en"

_EN = {
    # --- wspolne ---
    "Jezyk: PL": "Language: EN",
    "Ustawienia": "Settings",
    "Folder wyjsciowy": "Output folder",
    "Kroki:": "Steps:",
    "Zapisz ustawienia": "Save settings",
    "Zapisano ustawienia.": "Settings saved.",
    "Podglad": "Preview",
    "(brak)": "(none)",
    "Stop": "Stop",
    "Gotowe.": "Done.",
    "Zatrzymywanie...": "Stopping...",
    "Trwa generowanie": "Generation in progress",
    "Jezyk zmienisz po zakonczeniu generowania.": "You can change the language after generation finishes.",
    # --- Pan Kret Studio ---
    "Zrodlo generowania": "Generation source",
    "Lokalnie (Qwen-Image-2.1 / usluga)": "Local (Qwen-Image-2.1 / service)",
    "API (Google AI Studio - Gemini)": "API (Google AI Studio - Gemini)",
    "Klucz API:": "API key:",
    "pokaz": "show",
    "Model:": "Model:",
    "Opoznienie miedzy zapytaniami (s):": "Delay between requests (s):",
    "Klucz zdobedziesz na aistudio.google.com -> 'Get API key'. Trzymany lokalnie w config.json - nie wrzucaj go do gita.":
        "Get a key at aistudio.google.com -> 'Get API key'. Stored locally in config.json - never commit it to git.",
    "Qwen-Image-2.1 (folder)": "Qwen-Image-2.1 (folder)",
    "Prompty (.json)": "Prompts (.json)",
    "Seed:": "Seed:",
    "Chroma key (zielone)": "Chroma key (green)",
    "rembg (fallback)": "rembg (fallback)",
    "Seed grupy z pola:": "Group seed field:",
    "Podfoldery kategorii": "Category subfolders",
    "Wczytaj prompty...": "Load prompts...",
    "Przeladuj liste": "Reload list",
    "kategoria": "category",
    "status": "status",
    "Generuj zaznaczone": "Generate selected",
    "Generuj brakujace": "Generate missing",
    "Stop (po biezacym)": "Stop (after current)",
    "czeka": "waiting",
    "zrobione": "done",
    "generuje...": "generating...",
    "BLAD": "ERROR",
    "Brak pliku": "File not found",
    "Nie znaleziono:\n{path}": "Not found:\n{path}",
    "Blad JSON": "JSON error",
    "Nie udalo sie wczytac:\n{e}": "Could not load:\n{e}",
    "Wczytano {n} promptow z {plik}.": "Loaded {n} prompts from {plik}.",
    "Wybierz plik z promptami": "Choose a prompts file",
    "Wszystkie pliki": "All files",
    "(jeszcze nie wygenerowano)": "(not generated yet)",
    "(podglad: {e})": "(preview: {e})",
    "Nie znaleziono klienta Qwen 2.1:\n{plik}\n\nWskaz wlasciwy folder przyciskiem ...":
        "Qwen 2.1 client not found:\n{plik}\n\nPoint to the right folder with the ... button",
    "Brak klucza API": "No API key",
    "Wpisz klucz API (Google AI Studio) w polu 'Klucz API' powyzej.":
        "Enter your API key (Google AI Studio) in the 'API key' field above.",
    "Nic do zrobienia.": "Nothing to do.",
    "Usluga Qwen-Image-2.1 ({url}) - sprawdzam / uruchamiam (start do kilku minut)...":
        "Qwen-Image-2.1 service ({url}) - checking / starting (may take a few minutes)...",
    "Usluga Qwen gotowa.": "Qwen service ready.",
    "Brak klucza API.": "No API key.",
    "Polaczono z Google AI Studio API.": "Connected to Google AI Studio API.",
    "API nie zwrocilo obrazu (sprawdz klucz / limit zapytan / tresc prompta).":
        "The API returned no image (check the key / rate limit / prompt).",
    "BLAD: {e}": "ERROR: {e}",
    "BLAD ladowania modelu: {e}": "ERROR loading the model: {e}",
    "BLAD: brak biblioteki 'google-genai'. Zainstaluj w tym samym venv: pip install google-genai":
        "ERROR: 'google-genai' is missing. Install it in the same venv: pip install google-genai",
    "BLAD polaczenia z API: {e}": "ERROR connecting to the API: {e}",
    "Zatrzymano.": "Stopped.",
    "wysylanie do Qwen 2.1...": "sending to Qwen 2.1...",
    "wysylanie do API...": "sending to the API...",
    "tlo wyciete ({narzedzie})": "background removed ({narzedzie})",
    "Zatrzymanie po biezacym obrazku...": "Stopping after the current image...",
    # --- Pan Kret Edit Studio ---
    "Folder zrodel (refs)": "Source folder (refs)",
    "Manifest (.json)": "Manifest (.json)",
    "Rozmiar (np. 512 lub 512x288):": "Size (e.g. 512 or 512x288):",
    "Odswiez zrodla": "Refresh sources",
    "Zrodla (z folderu refs)": "Sources (from refs folder)",
    "plik": "file",
    "prompty": "prompts",
    "Prompty wybranego zrodla": "Prompts for the selected source",
    "id (nazwa pliku wynikowego)": "id (output file name)",
    "Przezroczyste (odetnij tlo)": "Transparent (remove background)",
    "Rozmiar zrodla:": "Source size:",
    "id wyniku:": "output id:",
    "prompt (instrukcja edycji):": "prompt (edit instruction):",
    "Dodaj / zmien prompt": "Add / update prompt",
    "Usun prompt": "Remove prompt",
    "Podglad ostatniego wyniku": "Latest result preview",
    "Generuj wszystko": "Generate all",
    "Generuj wybrane zrodlo": "Generate selected source",
    "Nie wczytano manifestu: {e}": "Could not load the manifest: {e}",
    "Zrodel: {n} w {folder}": "Sources: {n} in {folder}",
    "Wybierz zrodlo": "Choose a source",
    "Najpierw kliknij zrodlo na liscie po lewej.": "First click a source in the list on the left.",
    "Brak danych": "Missing data",
    "Podaj id wyniku i prompt.": "Enter an output id and a prompt.",
    "Zapisano prompt '{id}' dla {zrodlo}": "Saved prompt '{id}' for {zrodlo}",
    "Nic do zrobienia": "Nothing to do",
    "Wybierz zrodlo z przypisanymi promptami.": "Choose a source that has prompts.",
    "Pusto": "Empty",
    "Brak zrodel z promptami.": "No sources with prompts.",
    "[err] nie udalo sie uruchomic: {e}": "[err] could not start: {e}",
    # --- generuj.py / edit_backend.py ---
    "Usluga Qwen-Image-2.1 - sprawdzam / uruchamiam...": "Qwen-Image-2.1 service - checking / starting...",
    "pomijam (jest)": "skipping (exists)",
    "zapisano {plik}": "saved {plik}",
    "Zadan w manifescie: {n}, do zrobienia: {m}": "Jobs in manifest: {n}, to do: {m}",
    "usluga Qwen 2.1 ({url}) - sprawdzam / uruchamiam...": "Qwen 2.1 service ({url}) - checking / starting...",
    "usluga gotowa.": "service ready.",
    "BRAK ZRODLA {plik}": "SOURCE MISSING {plik}",
    "zapisano": "saved",
    "Koniec.": "Finished.",
    # --- tlo.py ---
    "[rembg] laduje model wycinania - przy pierwszym uzyciu na tym komputerze pobiera go z internetu (ok. 1 GB, kilka minut, postep widac w terminalu)":
        "[rembg] loading the cut-out model - on first use on this computer it is downloaded (about 1 GB, a few minutes, progress shown in the terminal)",
    "[rembg] model gotowy": "[rembg] model ready",
    "[chroma] wyciete tylko {ile} obrazka - tlo nie jest zielone": "[chroma] removed only {ile} of the image - background is not green",
    "[{narzedzie} nie wypalil] {e}": "[{narzedzie} failed] {e}",
    "UWAGA: tlo NIE zostalo wyciete - zapisano obrazek z tlem": "WARNING: background NOT removed - image saved with its background",
}


def _wczytaj():
    global _kod
    if os.environ.get("PKS_JEZYK") in ("pl", "en"):   # Edit Studio przekazuje swoj jezyk do edit_backend.py
        _kod = os.environ["PKS_JEZYK"]
        return
    try:
        with open(_PLIK, encoding="utf-8") as f:
            _kod = "pl" if json.load(f).get("jezyk") == "pl" else "en"
    except (OSError, ValueError):
        _kod = "en"


def kod():
    return _kod


def ustaw(nowy):
    """Zmienia jezyk i zapisuje wybor w jezyk.json."""
    global _kod
    _kod = "pl" if nowy == "pl" else "en"
    try:
        with open(_PLIK, "w", encoding="utf-8") as f:
            json.dump({"jezyk": _kod}, f)
    except OSError:
        pass


def t(tekst, **pola):
    """Tekst w wybranym jezyku; pola wstawia jak str.format."""
    wynik = _EN.get(tekst, tekst) if _kod == "en" else tekst
    return wynik.format(**pola) if pola else wynik


def postep(linia):
    """Linia postepu z uslugi Qwen ('krok 3/24  1.5 s/krok (zostalo ~30 s)') w wybranym jezyku."""
    if _kod != "en":
        return linia
    linia = re.sub(r"\bs/krok\b", "s/step", linia)
    linia = re.sub(r"\bkrok\b", "step", linia)
    return re.sub(r"\bzostalo\b", "left", linia)


_wczytaj()
