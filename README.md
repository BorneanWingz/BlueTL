# BlueTL — Manga Translation Desktop App

[![Version](https://img.shields.io/badge/version-v1.0.2-magenta)](https://github.com/BorneanWingz/BlueTL)
[![Platform](https://img.shields.io/badge/platform-Windows-blue)]()
[![License](https://img.shields.io/badge/license-MIT%20core%20%2F%20GPL--3.0%20component-green)](LICENSE.md)
[![OCR](https://img.shields.io/badge/OCR-local-orange)]()

<div align="center">
  <img src="assets/bluetl.png" alt="BlueTL icon" width="200" height="200">
  <h1>🔷 BlueTL</h1>
  <h3><em>Manga translation desktop app.</em></h3>
</div>

## About

BlueTL is a Windows PySide6 application for translating manga pages. It detects text
regions locally, recognises the text with Manga OCR, sends untranslated rows to any
OpenAI-compatible API provider, and exports TXT or DOCX results.

- Runs from source or as a portable PyInstaller folder.
- Local OCR does not require an API request.
- Translation requires an internet connection to the configured provider.
- No provider, API key, or model list is compiled into the executable.
- Settings are saved in `%APPDATA%\BlueTL\config.json`.
- API keys are protected with Windows DPAPI and are never stored as plaintext.


## Features

### Provider connection

Enter an OpenAI-compatible **Base URL** and **API key**, then press **Save**. The app
fetches the provider's `GET /models` response before enabling the Model picker. Editing
either connection field makes the connection stale and locks the picker until it is
confirmed again.

Provider model lists are cached per Base URL and restored on the next launch, including
when the provider is temporarily offline. A bare host such as `localhost:1234` receives
a scheme and `/v1` automatically. A model ID can also be typed manually.

**Free models only** filters fetched model IDs containing `free` (case-insensitive).
When a non-free model is selected, free models are attempted first, followed by the
selected model and then other models reported by the provider.

### Import and OCR

BlueTL accepts JPG, JPEG, PNG, WebP, and PSD images, plus ZIP and RAR archives containing
them. Files are ordered naturally by name, so `chapter-2.jpg` precedes `chapter-10.jpg`.
Layered PSD files are composited with `psd-tools`, including 16-bit documents, before OCR.

Text detection uses the vendored `comic_text_detector` package. Manga OCR is run only on
detected text blocks; a page with no detected block is reported as having no text instead
of sending the whole page to the OCR model. Damaged images are skipped while the rest of
the batch continues.

### Review and translation

- **Recognise OCR** runs local OCR without spending API tokens.
- **Translate all** recognises first when needed, then translates only rows without a translation.
- **Add row** inserts an editable row below the selected line.
- **Delete row** removes unwanted or hallucinated lines.

### Export

Translation rows can be exported to TXT or DOCX. Clearing a Translation cell makes that
row eligible for translation again.

## Interface

The Translator tab has a Connection card and a Job card. The Job card contains target
language, model refresh, API status, image status, and the primary Import, Recognise OCR,
and Translate all actions. Test API, export, and row-editing actions are grouped below.
The About tab shows version and author information and links to the public README and
optional [support page](https://buymeacoffee.com/DrLwSii).


## Run from source

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

## Build a portable executable

Run `build.ps1` from PowerShell in the repository root. The script installs dependencies,
checks the icon, version information, OCR models, and vendored detector, then runs
PyInstaller with the data-collection flags required by the frozen application.

```powershell
.\build.ps1
```

The output is `dist\BlueTL\BlueTL.exe`. The script also verifies that the bundled unidic
dictionary, detector weights, Transformers image-processing modules, and torchvision
compiled extensions are present. See [BUILD.md](BUILD.md) for the build procedure and
release contents.

## Model files

The Manga OCR model is expected under `assets\manga-ocr-model`. The detector weights are
expected at `assets\comic-text-detector-model\comictextdetector.pt` and are not committed
by Git. Download the detector weights from the release documented in
[`comic_text_detector/VENDOR.md`](comic_text_detector/VENDOR.md).

Both OCR stages are local. Translation through a remote API still requires internet access;
provider model names do not automatically provide downloadable local weights.

## Version history

### v1.0.2

- Redesigned interface with branded header, Connection card, and Job card.
- Expanded model picker and added the **No free models detected** warning.
- Added transparent icon background and Windows product/version metadata.
- Renamed the connection confirmation action to **Save**.

### v1.0.1

- Added explicit provider confirmation and model discovery through `GET /models`.
- Added saved providers per Base URL and DPAPI-protected API-key storage.
- Added the **Free models only** filter.
- Added PSD support, including PSD files inside ZIP/RAR archives.
- Fixed startup failures caused by non-ASCII or damaged UTF-8 settings files.

## Credits

BlueTL was informed by the architecture and documentation of these MIT-licensed projects:

- [KŌMA Studio](https://git.mitgai.net/klaus-2/koma-studio)
- [manga-translation](https://github.com/M3MONs/manga-translation)
- [Lumina](https://github.com/lumina-tl/lumina)

BlueTL uses PySide6, OpenAI's Python client, python-docx, Pillow, Manga OCR,
OpenCV, PyTorch/torchvision, psd-tools, rarfile, and the vendored comic-text-detector.
Their respective licenses remain applicable. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

The BlueTL application code is released under the MIT License. The vendored
`comic_text_detector\` component is GPL-3.0; distributed builds containing it must comply
with GPL-3.0 and provide the complete corresponding source. See [LICENSE.md](LICENSE.md).

---

*BlueTL · Version v1.0.2 · Author: Blue-Wingz @ facedesk · Published by borneanwingz.fl*

