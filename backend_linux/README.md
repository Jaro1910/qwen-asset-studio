# Pan Kret Studio – backend (Linux)

Narzędzia do generowania grafik do gry z plików z promptami (`*.json`):

| Program | Uruchomienie | Do czego |
|---|---|---|
| **Pan Kret Studio** | `./run.sh` | GUI: wczytuje plik z promptami (np. `01_common_ui.json`) i generuje grafiki |
| **Pan Kret Edit Studio** | `./run_edit_ui.sh` | GUI: edycja istniejących obrazków (obraz referencyjny + prompt), manifest `edits.json` (tworzy go samo) |
| `generuj.py` | `./venv/bin/python generuj.py` | to samo co Studio, ale bez okna (ścieżki w nagłówku pliku) |
| `edit_backend.py` | `./venv/bin/python edit_backend.py --manifest ../edits.json` | to samo co Edit Studio, bez okna (`--dry-run` pokazuje, co jest do zrobienia) |
| `tlo.py` | (nie uruchamia się go) | wspólne wycinanie tła dla wszystkich programów powyżej |
| `jezyk.py` | (nie uruchamia się go) | język interfejsu PL / EN dla wszystkich programów powyżej |

Pliki z promptami i manifesty (`*.json`) leżą katalog wyżej, obok folderu `backend_linux/`.

**Język interfejsu:** przycisk **Language: EN / Jezyk: PL** w prawym górnym rogu obu okien przełącza angielski
i polski od razu (pola, lista i log zostają). Wybór zapisuje się w `backend_linux/jezyk.json` i obowiązuje też
`generuj.py` i `edit_backend.py`. Bez tego pliku programy startują po angielsku. Podczas generowania przełączanie
jest zablokowane.

### Manifesty-wzory w paczce

Siedem gotowych plików z promptami z gry *Crusader Defence*, wygenerowanych tym backendem. Każdy pokazuje inny rodzaj
grafiki – skopiuj ten, który pasuje, i podmień w nim treść promptów na własną:

| Plik | Co pokazuje |
|---|---|
| `01_common_ui.json` | elementy interfejsu: przyciski, panele, ikony (przezroczyste tło) |
| `05_heroes.json` | postacie: portrety i sprite'y bojowe (4 klatki w jednym pasku) |
| `06_temple.json` | budynek w kilku poziomach rozbudowy (pojedyncze obrazki) |
| `07_maps_tilesets.json` | tła map (pełne tło), przeszkody i sieć ścieżek do pocięcia na kafle |
| `11_cutscenes_heroes_store.json` | slajdy / ilustracje do scenek (pionowe 1080×1920, pełne tło) i grafiki do sklepu |
| `13_enemies_3x3_v18.json` | animacje postaci: 3 klatki w jednym pasku (chód, płonięcie, spowolnienie) |
| `14_swarog_miotacz.json` | budynek z animacją: wieża w kilku poziomach i odmianach, 5 klatek animacji w jednym pasku |

Każda grafika z przezroczystym tłem ma w prompcie zdanie **„Transparent background on #00FF00.”** – dzięki temu tło
wycina chroma key (patrz „Przezroczyste tło”). Trzymaj się tego we własnych promptach.

Manifestów edycji paczka nie zawiera: Edit Studio tworzy `edits.json` samo przy pierwszym zapisie (format niżej).

---

## Jak to działa (jakie modele i jak są wywoływane)

```
GUI / skrypt  ──>  qwen21.py  ──>  ubnt_qwen_client.py  ──HTTP 127.0.0.1:8010──>  ubnt_qwen_service.py  ──>  Qwen-Image-2.1 (GPU)
 (venv backendu)                     (tylko stdlib)                                 (osobny venv Qwena)
```

- **Model lokalny: Qwen-Image-2.1** (`Qwen/Qwen-Image-2.1` z HuggingFace, ok. 32 GB wag). Ten jeden model generuje
  obrazy z tekstu (endpoint `/generate`) i edytuje obrazy z referencją (endpoint `/edit`).
  Ładuje go diffusers (`QwenImage21Pipeline`) w bf16. Text encoder to Qwen3-VL, jest w tym samym folderze modelu.
- Model działa jako **lokalna usługa HTTP** (`ubnt_qwen_service.py`, FastAPI, port 8010). Nie trzeba jej uruchamiać ręcznie:
  przy pierwszym generowaniu klient sam ją odpala w tle i czeka, aż model się załaduje (do kilku minut). Po 10 min
  bezczynności usługa sama się zamyka i zwalnia GPU. Log: `ubnt_qwen_service.log` w folderze modelu.
- Usługa robi jedno zadanie naraz, kolejne czekają w kolejce. Przyjmuje boki 512–1792 px podzielne przez 32.
  `qwen21.py` sam dobiera taki rozmiar w tych samych proporcjach, a potem skaluje wynik do rozmiaru z pliku
  z promptami (np. sprite 256×256 jest generowany w 512×512 i zmniejszany).
- **Tryb API (opcjonalny):** w Pan Kret Studio można zamiast modelu lokalnego wybrać Google AI Studio (Gemini,
  domyślnie `gemini-2.5-flash-image`). Potrzebny jest klucz z aistudio.google.com. Klucz zapisuje się w `config.json`,
  nie udostępniaj tego pliku.
- **Przezroczyste tło** (`tlo.py`, jeden kod dla Studio, `generuj.py` i edycji, więc ten sam prompt daje ten sam wynik):
  - Grafiki z `"background": "transparent..."` najlepiej generować na jednolitej zieleni (`#00FF00` w prompcie).
  - **Model lokalny:** najpierw chroma key (wycina zieleń). Jeśli wytnie mniej niż 5% obrazka, znaczy to, że tło nie
    było zielone (np. prompt nie prosił o `#00FF00`), i tło wycina `rembg`.
  - **Tryb API (Gemini):** najpierw `rembg`, chroma key jest ratunkiem, gdy `rembg` zgłosi błąd.
  - **Edycja** (Edit Studio, `edit_backend.py`): tylko `rembg`.
  - `rembg` przy pierwszym użyciu na danym komputerze pobiera model (ok. 1 GB), potem wczytuje go raz na uruchomienie
    programu. Wynik trafia do folderu wyjściowego dopiero po wycięciu tła, więc przerwana praca nie zostawia
    pliku, który **Generuj brakujące** uznałby za gotowy.
  - Gdy żadne narzędzie nie zadziała (albo oba są wyłączone w GUI), zapisuje się obrazek **z tłem**, a w logu pojawia
    się `UWAGA: tlo NIE zostalo wyciete`. Log pokazuje też przy każdej grafice, którym narzędziem wycięto tło.
  - **Chroma key z maską:** program wyznacza kontur obiektu i wypełnia jego wnętrze. Zieleń **otoczona** obiektem
    zostaje (np. zielony pasek w ramce, oczy, trawa nad literami), a dziury w kolorze tła są przezroczyste (np. środek
    litery, prześwit między gałązkami). Krawędź maski jest miękka na 2 px (`KRAWEDZ_PX` w `tlo.py`; szersza rozmywa
    sprite'y i gubi cienkie detale).
  - **Ograniczenie:** zielony fragment, który **wystaje poza sylwetkę** obiektu (np. listek na brzegu), jest wycinany
    razem z tłem. Trzeba go uzupełnić ręcznie albo dać tej grafice `rembg` (odznaczyć „Chroma key” w GUI).
  - W trybie API wymóg „całe tło jednolicie zielone” jest dopisywany do promptu tylko grafikom z przezroczystym tłem.
    Grafiki z pełnym tłem (np. łąka z „green grass”) idą bez tego dopisku.

---

## Wymagania

- Linux (testowane na Ubuntu 24.04), Python 3.11+ (testowane na 3.11 i 3.12). `rembg` i `onnxruntime` w obecnych
  wersjach nie instalują się na Pythonie 3.10 (domyślny w Ubuntu 22.04).
- Karta NVIDIA ze sterownikiem obsługującym CUDA 12.8. Domyślna konfiguracja usługi zakłada **dwie karty**:
  RTX 3090 24 GB (`cuda:0`: transformer + VAE) i RTX 3080 20 GB (`cuda:1`: text encoder). Przy innym sprzęcie zmień
  `MAX_MEMORY` w `ubnt_qwen_service.py` (patrz krok 2.4).
- Ok. 35 GB miejsca na model (najlepiej na dysku NVMe) i ok. 10 GB na venv-y.

---

## Instalacja

### 1. Paczki systemowe

```bash
sudo apt install python3-venv python3-tk git
```

`python3-tk` jest potrzebny do okien GUI, a `git` do instalacji diffusers z repozytorium.

### 2. Model Qwen-Image-2.1 i jego usługa (jednorazowo)

**2.1. Utwórz folder modelu i skopiuj do niego pliki usługi** (z folderu `backend_linux/`):

```bash
mkdir -p /models/models/qwen-image-2.1
cp qwen_service/* /models/models/qwen-image-2.1/
```

Folder może być w innym miejscu (najlepiej na dysku NVMe) – wtedy podmieniaj ścieżkę w kolejnych krokach.

**2.2. Utwórz venv Qwena.** Musi się nazywać `venv-linux` i leżeć w folderze modelu, bo tam szuka go klient:

```bash
cd /models/models/qwen-image-2.1
python3 -m venv venv-linux
./venv-linux/bin/pip install --upgrade pip
./venv-linux/bin/pip install -r req-linux-torch.txt   # najpierw torch 2.11 dla CUDA 12.8
./venv-linux/bin/pip install -r req-linux.txt         # diffusers (konkretny commit z gita), transformers, fastapi, uvicorn...
```

`QwenImage21Pipeline` jest na razie tylko w tej wersji diffusers z gita, więc nie zmieniaj tego wpisu na wydanie z PyPI.

**2.3. Pobierz wagi** (ok. 32 GB). Narzędzie `hf` instaluje się razem z `req-linux.txt` (paczka `huggingface_hub`),
więc nie trzeba niczego instalować systemowo (na Ubuntu 24.04 systemowy `pip install` i tak odmawia:
`externally-managed-environment`). Nadal w folderze modelu:

```bash
./venv-linux/bin/hf download Qwen/Qwen-Image-2.1 --local-dir .
```

W folderze powinny być `model_index.json` oraz podfoldery `transformer/`, `text_encoder/`, `vae/`, `processor/` i `scheduler/`.

**2.4. Ustaw konfigurację w `ubnt_qwen_service.py`** (sekcja `# ---- KONFIG ----`):

| Zmienna | Co ustawić |
|---|---|
| `MODEL_DIR` | folder modelu z kroku 2.1, np. `"/models/models/qwen-image-2.1"` |
| `OUT_DIR` | folder roboczy usługi. Backend i tak przenosi każdy obraz do swojego folderu wyjściowego i kasuje kopię usługi |
| `MAX_MEMORY` | VRAM na kartę, np. `{0: "18GB", 1: "22GB"}`. Na jednej karcie 48 GB lub większej: `{0: "40GB"}` |
| `PORT` | domyślnie 8010. Jeśli zmienisz, ustaw ten sam `URL` w `ubnt_qwen_client.py` |

**2.5. Test** (opcjonalny). Po wpisaniu `Usluga gotowa` przerwij Ctrl+C:

```bash
./venv-linux/bin/python ubnt_qwen_service.py
```

### 3. Backend

```bash
cd backend_linux
./setup.sh
```

Skrypt tworzy `venv/` i instaluje `pillow`, `numpy`, `scipy`, `rembg`, `onnxruntime` i `google-genai` (lista w `requirements.txt`).
Backend nie potrzebuje torcha. Cały model działa w venv Qwena.

Jeśli model leży gdzie indziej niż `/models/models/qwen-image-2.1`, podaj jego folder w GUI: w Pan Kret Studio pole
**Qwen-Image-2.1 (folder)** (zapisuje się w `config.json`), w Edit Studio pole **Qwen-Image-2.1** (zapisuje się w
`config_edit.json` i w manifeście jako `qwen_dir`). Dla `generuj.py` i ręcznie pisanych manifestów ustaw zmienną środowiskową:

```bash
export QWEN21_DIR=/sciezka/do/qwen-image-2.1
```

---

## Użycie

1. `./run.sh`
2. Ustaw **Prompty (.json)** (np. `../01_common_ui.json`) i **Folder wyjściowy** (domyślnie `~/backends/output/pan-kret-studio`), potem kliknij **Zapisz ustawienia**.
3. Wybierz **Generuj brakujące** albo zaznacz pozycje i wybierz **Generuj zaznaczone**. Pierwsze generowanie czeka, aż model się załaduje.
   Gotowe pliki są pomijane, więc można przerwać pracę i wrócić do niej później.

Pola w Pan Kret Studio:
- **Kroki:** liczba kroków generowania (domyślnie 24).
- **Seed:** pusty oznacza losowy wynik.
- **Seed grupy z pola:** np. `category` daje spójny wygląd w obrębie jednej kategorii.
- **Podfoldery kategorii:** zapisuje wyniki do `out_dir/<category>/`.
- **Chroma key (zielone)** / **rembg (fallback)**: które narzędzia wycinania tła wolno użyć (opis kolejności wyżej,
  w „Przezroczyste tło”).

Edit Studio:
1. Wskaż **Folder źródeł (refs)** z obrazkami.
2. Kliknij źródło, wpisz id wyniku i prompt, a potem **Dodaj / zmień prompt**. Manifest zapisuje się sam.
3. Wybierz **Generuj**.

---

## Pliki z promptami i manifesty – jak karmić backend

Są dwa rodzaje plików JSON:

- **plik z promptami** dla Pan Kret Studio i `generuj.py`: lista obrazków do wygenerowania od zera,
- **manifest edycji** dla Edit Studio i `edit_backend.py`: lista obrazków do przerobienia na podstawie istniejących grafik.

### Plik z promptami (np. `01_common_ui.json` … `14_swarog_miotacz.json`)

Lista obrazków jest pod kluczem `"assets"` albo `"prompts"`. Oba warianty działają.

```json
{
  "global": {
    "negative": "text, letters, words, watermark, signature, logo"
  },
  "assets": [
    {
      "id": "mole_idle",
      "category": "mole",
      "aspect_ratio": "1:1",
      "background": "transparent",
      "prompt": "Cute cartoon mole character for a 2D mobile game, standing front view. Dark purple-grey velvety fur, cream muzzle and belly, small pink nose, tiny black eyes, yellow miner helmet with a lamp. Flat vector cel-shading, thick clean dark-brown outlines. Whole character centered on a #00FF00 background.",
      "negative": "text, extra limbs, realistic photo"
    }
  ]
}
```

| Pole | Wymagane | Działanie |
|---|---|---|
| `id` | tak | Nazwa pliku wynikowego (`<id>.png`). Musi być unikalna. Jeśli plik już istnieje w folderze wyjściowym, obrazek jest pomijany przy **Generuj brakujące** |
| `prompt` | tak | Opis obrazka po angielsku. Wpis `#00FF00` jest automatycznie zamieniany na opis zielonego tła, bo inaczej model potrafi namalować go jako napis (dotyczy też promptów edycji) |
| `negative` | nie | Czego ma nie być na obrazku. Pusty lub `" "` oznacza `global.negative`, a jeśli i tego brak, pole „default_negative” z `config.json` |
| `resolution` | nie | Dokładny rozmiar pliku, np. `"768x1024"`. Ma pierwszeństwo przed `aspect_ratio` |
| `aspect_ratio` | nie | Proporcje, np. `"1:1"` (1024×1024), `"16:9"` (1280×720) albo dowolne `"W:H"` (ok. 1 Mpx). Domyślnie `1:1`. Dłuższy bok ma najwyżej 1440 px |
| `background` | nie | Jeśli zawiera słowo `transparent`, tło jest wycinane i powstaje PNG z przezroczystością (patrz „Przezroczyste tło”). Prompt powinien wtedy prosić o jednolite zielone tło (`#00FF00`). Bez zielonego tła wycina je `rembg` |
| `category` | nie | Kolumna w GUI. Przy włączonych **Podfolderach kategorii** wynik trafia do `out_dir/<category>/` |
| `seed` | nie | Stały seed tego obrazka. Ma pierwszeństwo przed seedem z GUI |
| `category` jako grupa | nie | Wpisane w **Seed grupy z pola** (`category`) sprawia, że obrazki z tą samą wartością dostają ten sam seed, czyli bardziej spójny wygląd. Działa, tylko gdy w GUI jest też ustawiony **Seed** |

**Każdy `prompt` jest samowystarczalny:** zawiera pełny opis stylu, postaci, kolorów, tła i klatek animacji.
Dzięki temu każdy obrazek można wygenerować osobno, a powtarzanie tego samego opisu postaci w każdym prompcie
daje spójny wygląd między obrazkami. Qwen przy krótkich, ogólnikowych promptach zmyśla szczegóły. Zamiast „biedronka”
napisz np. „okrągły owad z czerwonymi pokrywami skrzydeł w czarne kropki, czarna głowa z dwoma białymi plamkami…”.

**Dodatkowe pola** w manifestach-wzorach (`note`, `style_reference` w `global`; `tileable`, `frames`, `frame_resolution`,
`frame_states`, `frame_size`, `state`, `hero`, `god`, `unit_class` itp. przy grafikach) to opisy dla człowieka i dla
silnika gry. Backend ich nie czyta: liczą się tylko pola z tabeli powyżej, a styl i układ klatek muszą być opisane
w samym `prompt`. Wyjątek: w **Seed grupy z pola** można wpisać dowolne pole, także dodatkowe (np. `unit_class`).

**Nowy zestaw grafik:** stwórz plik JSON według wzoru powyżej, w GUI kliknij **Wczytaj prompty...**, a potem **Generuj brakujące**.
Żeby wygenerować obrazek jeszcze raz, usuń jego plik `<id>.png` z folderu wyjściowego albo zaznacz go na liście i wybierz **Generuj zaznaczone**.

### Manifest edycji (np. `edits.json`)

Służy do przerabiania istniejących obrazków, np. ta sama postać w innej pozie albo klatki animacji z jednej grafiki.
Edit Studio tworzy i zapisuje go samo, ale można go też napisać ręcznie:

```json
{
  "src_dir": "refs",
  "out_dir": "output",
  "steps": 25,
  "jobs": [
    {
      "source": "mole_idle.png",
      "size": [512, 512],
      "transparent": true,
      "outputs": [
        { "id": "mole_dig_side", "prompt": "Keep this exact mole character unchanged - same fur, helmet and colors. Show it from the side, digging with both front paws. Solid #00FF00 background." },
        { "id": "mole_wave",     "prompt": "Keep this exact mole character unchanged. It waves its right paw. Solid #00FF00 background.", "size": [512, 288] }
      ]
    }
  ]
}
```

| Pole | Działanie |
|---|---|
| `src_dir` / `out_dir` | Folder z obrazkami źródłowymi i folder wyników. Ścieżka względna (np. `refs`) liczy się od folderu, w którym leży manifest. GUI nadpisuje je wartościami z pól ustawień. W trybie bez okna można je nadpisać opcjami `--src-dir` i `--out-dir` |
| `steps` | Liczba kroków (domyślnie 20) |
| `qwen_dir` | Folder modelu Qwen-Image-2.1. Edit Studio wpisuje go sam (pole **Qwen-Image-2.1**). Brak pola = zmienna `QWEN21_DIR` albo domyślny `/models/models/qwen-image-2.1` |
| `jobs[].source` | Nazwa pliku źródłowego w `src_dir` |
| `jobs[].size` | Rozmiar wyników `[szer, wys]`. Pojedynczy wynik może mieć własne `size` |
| `jobs[].transparent` | `true` oznacza, że tło wyników jest wycinane przez `rembg`. Brak pola w ręcznie pisanym manifeście = `false`. Edit Studio przy nowym źródle ustawia domyślnie `true` (pole „Przezroczyste (odetnij tlo)”) |
| `outputs[].id` | Nazwa pliku wynikowego (`<id>.png`). Gotowe pliki są pomijane |
| `outputs[].prompt` | Polecenie edycji. Dobrze działa schemat: „Keep this exact character unchanged – … Show it …” |


Sprawdzenie bez generowania (gdy `edits.json` już istnieje): `./venv/bin/python edit_backend.py --manifest ../edits.json --dry-run`

---

## Problemy

| Objaw | Rozwiązanie |
|---|---|
| `No module named 'tkinter'` | `sudo apt install python3-tk`, potem usuń `venv/` i uruchom `./setup.sh` jeszcze raz |
| `Brak ubnt_qwen_client.py w ...` | Zły folder modelu: popraw pole w GUI albo `QWEN21_DIR` |
| `Usluga Qwen nie wystartowala ...` | Przeczytaj `ubnt_qwen_service.log` w folderze modelu. Zwykle przyczyną jest brak venv `venv-linux`, zły `MODEL_DIR` albo za mało VRAM |
| `Qwen HTTP 507` | Za mało pamięci GPU dla tej rozdzielczości. Zmniejsz `resolution` w pliku z promptami albo popraw `MAX_MEMORY` |
| Port 8010 zajęty przez inny program | Zmień `PORT` w usłudze i `URL` w kliencie na ten sam |
| `UWAGA: tlo NIE zostalo wyciete` | Tło nie było zielone, a `rembg` jest wyłączony w GUI albo nie działa (`[rembg nie wypalil] ...` w logu). Włącz „rembg” albo popraw instalację (`./setup.sh`) |
| `[chroma] wyciete tylko ...% obrazka` | Informacja, nie błąd: tło nie było zielone, wycinanie przejmuje `rembg` |
| Po `[rembg] laduje model wycinania` długo nic się nie dzieje | Przy pierwszym użyciu `rembg` pobiera swój model (ok. 1 GB, do `~/.rembg/models/`). Postęp widać w terminalu, w którym uruchomiono `./run.sh`. Nie zamykaj programu, dopóki nie pojawi się `[rembg] model gotowy` |
| Brak zielonego fragmentu na brzegu obiektu | Chroma key wycina zieleń wystającą poza sylwetkę (patrz „Przezroczyste tło”) |
