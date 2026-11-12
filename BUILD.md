# BlueTL — Build and Release Notes

**Current version: v1.0.2**

This document lists the changelog of BlueTL and what is inside a released build.

---

## 1. Release history

### Version v1.0.2

- Redesigned the interface around a branded header, a Connection card and a Job card.
- Widened the Model picker to the full Connection card width and moved the
  **Free models only** checkbox to its right.
- Added a **"No free models detected."** popup when the free-model filter is ticked and
  no model ID in the fetched list contains `free`.
- Made the icon's outer background transparent.
- Filled in Windows executable properties (product name, file and product versions)
  from `version_info.txt`.
- Relabelled the connection confirmation button to **Save**.
- The About tab now links to the public README and includes an optional support link.

### Version v1.0.1

- Added the Cline-style provider connection with an explicit confirmation step: the
  Base URL and API key are only a draft until **Save** is pressed, which fetches the
  model list and unlocks the Model dropdown. Editing either field marks the connection
  stale and re-locks the dropdown.
- Removed the hard-coded provider from the executable: the fields start empty and
  everything is remembered in `%APPDATA%\BlueTL\config.json`.
- Added the **Free models only** tick box, which narrows the dropdown to model IDs
  containing `free` (case-insensitive) without another network request.
- Added saved providers per Base URL: each Base URL is its own profile with its own
  key, model list and chosen model. An API key is stored DPAPI-protected only after a
  model list was fetched successfully with it.
- Added PSD support: layered Photoshop `.psd` pages (directly or inside ZIP/RAR
  archives) are composited with `psd-tools` before text detection, including 16-bit
  documents that Pillow's built-in PSD plugin rejects.
- Fixed the startup crash with a non-ASCII settings file: the config is now read back
  as UTF-8, matching how it is written, and a damaged or unreadable config is treated
  as a missing one instead of blocking startup.

### Version v1.0.0 (initial commit)

- Added the BlueTL app source, icon assets, build script and the complete README.
- Added the vendored comic-text-detector package with the compact single-row action bar.

---

## 2. Building from source

### Prerequisites

- Windows with Python 3.14 (`py -3` must resolve on the build machine).
- An internet connection for the first dependency install.

### Model files that must be in place before building

PyInstaller packages whatever is present at build time, so the two OCR model folders
must exist before `build.ps1` runs. The script fails loudly when either is missing:

| Item | Expected location |
| --- | --- |
| Manga OCR model | `assets\manga-ocr-model` (must contain `vocab.txt`) |
| Text detection weights | `assets\comic-text-detector-model\comictextdetector.pt` |
| App icon | `assets\bluetl.png` |
| Windows version information | `version_info.txt` |
| Vendored detector package | `comic_text_detector\inference.py` |

The text-detection weights are not committed (see `.gitignore`) and are downloaded once
from the manga-image-translator release `beta-0.2.1`:

```text
https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.2.1/comictextdetector.pt
```

Place the file in `assets\comic-text-detector-model\`, exactly like the Manga OCR model
folder.

### Running the build

```powershell
.\build.ps1
```

The script:

1. Upgrades pip and installs `requirements.txt` under `py -3.14`.
2. Verifies the icon, version information, both OCR model folders and the vendored
   detector package are present, and stops the build if anything is missing.
3. Runs PyInstaller as a one-folder build with `--windowed --noupx` and the
   data-collection flags the frozen build needs:
   - `--collect-data unidic_lite` bundles the ~260 MB Japanese dictionary, without
     which the frozen app fails with "Unable to load vocabulary from file".
   - `--collect-data manga_ocr` bundles `manga_ocr\assets\example.jpg`, which
     MangaOcr opens in `__init__`.
   - `--collect-submodules comic_text_detector` bundles the vendored detector
     package, which `app.py` imports lazily inside a function.
   - `--collect-all psd_tools` bundles the PSD compositing helpers.
   - `--collect-all transformers` is required because transformers 5.x resolves
     classes such as ViTImageProcessor through lazy imports.
   - `--collect-all torchvision` forces the compiled `_C_stable`/`image_stable`
     extensions into the bundle.
4. Verifies after the build that the unidic dictionary, the detector weights, the
   transformers image-processing modules and the torchvision compiled extensions were
   actually bundled, and fails if any are missing.

### Build output

The finished product is one self-contained folder:

| Item | What it is |
| --- | --- |
| `dist\BlueTL\BlueTL.exe` | The main program window. |
| `dist\BlueTL\_internal\` | The Python runtime, libraries and bundled assets. |
| `dist\BlueTL\_internal\assets\manga-ocr-model\` | The bundled Manga OCR weights. |
| `dist\BlueTL\_internal\assets\comic-text-detector-model\` | The bundled text-detection weights. |
| `dist\BlueTL\_internal\unidic_lite\dicdir\` | The bundled Japanese tokenizer dictionary. |

Windows executable properties (product name `BlueTL`, file and product versions from
`version_info.txt`) are filled in during packaging. `%APPDATA%\BlueTL\config.json` is
created on first run of the built app, not committed to the repository.

---

## 3. Release checklist

Before tagging a release:

1. Update the version in `version_info.txt` (both `filevers`/`prodvers` and the
   `FileVersion`/`ProductVersion` strings).
2. Add the release notes to the version history above.
3. Run `build.ps1` and confirm it completes without error.
4. Launch `dist\BlueTL\BlueTL.exe` and confirm the app opens and OCR runs.
