# BlueTL — Manga Translation Desktop App

[![Version](https://img.shields.io/badge/version-v0.1.6-magenta)](https://github.com/BorneanWingz/BlueTL/blob/main/BUILD.md)
[![Platform](https://img.shields.io/badge/platform-Windows-blue)]()
[![License](https://img.shields.io/badge/license-MIT%20core%20%2F%20GPL--3.0%20component-green)](LICENSE.md)

<div align="center">
  <img src="assets/bluetl.png" alt="BlueTL icon" width="200" height="200">
  <h1>🔷 BlueTL</h1>
  <h3><em>Manga translation desktop app.</em></h3>
</div>

## About

BlueTL is a Windows PySide6 application for translating manga pages. It detects text
regions locally, recognises the text with Manga OCR, sends untranslated rows to any
OpenAI-compatible API provider, and exports TXT, DOCX, or PDF results.

- Runs from source or as a portable PyInstaller folder.
- Local OCR does not require an API request.
- Translation requires an internet connection to the configured provider.
- No provider, API key, or model list is compiled into the executable.
- Users are responsible for obtaining and configuring their own providers and API keys.
- Settings are saved in `%APPDATA%\BlueTL\config.json`.
- API keys are protected with Windows DPAPI and are never stored as plaintext.
- Output is machine-generated and may be wrong; review it before you rely on it.

## Quick Start (Windows Portable)

1. Download the latest release archive from the [Releases](https://github.com) page and extract the entire folder.
2. Run `BlueTL.exe` (no installation required).
3. Enter your OpenAI-compatible **Base URL** and **API key**, then press **Save**.

## Responsive OCR (v0.1.6+)

OCR now runs on a background thread. The window stays fully responsive while pages are being recognised — you can scroll the table, resize the window, or press **Stop** at any time. Completed rows appear incrementally as each page finishes. Model memory (~500 MB) is released automatically after the batch ends.


**This app is not signed with Windows certificate, as with most self-developed executables, so Windows or antivirus software may show a false-positive warning.**

## Machine Translation Disclaimer

**BlueTL produces machine translations. The output is generated automatically by OCR and
an AI language model, so it can be inaccurate, incomplete, or misleading, and it may
misread names, jokes, cultural references, sound effects, or implied meaning.**

**Review and edit every line before publishing, redistributing, or relying on it. You use
this software and its output at your own risk. The author accepts no responsibility or
liability for errors, mistranslations, or any loss arising from use of the software or its
output.**

## Features

### Provider connection

Enter an OpenAI-compatible **Base URL** and **API key**, then press **Save**. The app
fetches the provider's `GET /models` response before enabling the Model picker. Editing
either connection field makes the connection stale and locks the picker until it is
confirmed again.

Provider model lists are cached per Base URL and restored on the next launch, including
when the provider is temporarily offline. A bare host such as `localhost:1234` receives
a scheme and `/v1` automatically. A model ID can also be typed manually.

**Free models only** filters fetched model IDs containing `free` (case-insensitive). If no
fetched model ID matches, the app says so and unticks the box, restoring the full list.
When a non-free model is selected, free models are attempted first, followed by the
selected model and then other models reported by the provider.

### Import and OCR

BlueTL accepts JPG, JPEG, PNG, WebP, and PSD images, plus ZIP, RAR, and 7Z archives
containing them. **Import** opens a picker with two choices: **Select files...** accepts
several files at once, and **Select a folder...** imports exactly one folder, scanned
recursively, so a directory of pages or a parent folder holding one sub-folder per chapter
both work. Files are ordered naturally by name, so `chapter-2.jpg` precedes
`chapter-10.jpg`. Layered PSD files are composited with `psd-tools`, including 16-bit
documents, before OCR.


Text detection uses the vendored `comic_text_detector` package. Manga OCR is run only on
detected text blocks; a page with no detected block is reported as having no text instead
of sending the whole page to the OCR model. Damaged images are skipped while the rest of
the batch continues.

### Review and translation

- **Recognise OCR** runs local OCR without spending API tokens.
- **Translate all** recognises first when needed, then translates only rows without a translation.
- **Stop** sits beside **Translate all** and interrupts whichever batch is running. Because
  Translate all runs OCR first when needed, Stop cancels both phases. Work already finished
  is kept: recognised rows stay in the table and finished translations are not discarded.
  The in-flight page or request always completes first, so the status line reads
  *Stopping after the current step...* until the batch unwinds.
- **Add row** inserts an editable row below the selected line.
- **Delete row** removes unwanted or hallucinated lines.

If the chosen model, or one of the fallback models, runs out of free tokens or reaches its
request limit, a popup names the affected models and explains what to do next. It replaces
the generic failure dialog and is shown once per batch rather than once per row.

The detector and OCR model are released when a batch finishes, so the app does not keep
roughly half a gigabyte of model memory resident while you review or translate. The next
batch reloads them, which costs about a second.

### Export

One **Export** button opens a save dialog whose file-type picker chooses the format:
**PDF**, **Word (DOCX)**, or **plain text (TXT)**. The chosen filter decides the writer, so
the file name and the format always agree. PDF output paginates the table onto A4 pages at
150 DPI and wraps long lines inside their column. Clearing a Translation cell makes that row
eligible for translation again.


## Interface

The left navigation contains Translate, Control Panel, and About. Each page has its own icon
and a horizontal label. Use **<<** at the bottom of the sidebar to collapse it to icons only
(labels stay in the tooltips), and **>>** to expand it again. Translate keeps the compact
provider summary inside Translation Settings alongside model refresh, API status, image status,
and the primary Import, Recognise OCR, Translate all, and Stop actions. Test API, Export, and
row-editing actions are grouped below. Control Panel contains the full provider connection editor
and the default output-language and export-format pickers. The export dialog remains fully selectable
for each export; the saved format is only the initial selection. About shows version and author
information and links to
the public README and optional [donation page](https://buymeacoffee.com/DrLwSii).


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

**Current version: v0.1.6**

### v0.1.6

- **OCR runs on a background thread** — the UI stays fully responsive during recognition. You can scroll the table, resize the window, and press **Stop** at any time. Rows appear incrementally as each page finishes. Model memory (~500 MB) is released automatically after the batch ends.
- Stop button now interrupts OCR immediately (previously only between pages).

### v0.1.5

Changes made from 15 November 2026 at 00:00 through this release:

- Added left-side navigation with **Translate**, **Control Panel**, and **About**; renamed
  **Translator** to **Translate**.
- Moved provider configuration into Control Panel while retaining its compact status summary
  inside Translation Settings.
- Added persisted default output-language and export-format pickers. Export still offers PDF,
  DOCX, and TXT every time; the default only controls the initial selection and file extension.
- Added interruptible OCR and translation with a **Stop** button that preserves completed work.
- Added a consolidated reminder when free tokens, credits, quotas, or request limits are exhausted.
- Changed Import to explicit file/folder choices and kept BlueTL folder imports to one flat folder.
- Added bilingual target-language labels and expanded automated regression coverage.

### v1.0.4

- Fixed the translation table: a selected or edited cell no longer paints over its text, so
  the row stays readable while you click or type in it.
- **Free models only** now unticks itself after the "No free models detected." message, so the
  dropdown returns to the provider's full list instead of staying empty.
- Replaced the separate **Export TXT** and **Export DOCX** buttons with one **Export** button
  whose save dialog offers PDF, DOCX, or TXT.
- Added PDF export, rendered with Pillow so no new dependency is needed.

### v1.0.3

- Import a whole folder: cancelling the file dialog opens a folder picker that scans
  flatly, so a chapter directory or a parent folder of per-chapter sub-folders both work.
- Added 7Z archive support alongside ZIP and RAR.
- The detector and OCR model are released when a batch finishes, so the app no longer keeps
  roughly half a gigabyte of model memory resident while you review or translate.
- Capped the PyTorch CPU thread pool, which reduces the memory cost of the OCR runtime.

## Credits

BlueTL was informed by the architecture and documentation of these MIT-licensed projects:

- [KŌMA Studio](https://git.mitgai.net/klaus-2/koma-studio)
- [manga-translation](https://github.com/M3MONs/manga-translation)
- [Lumina](https://github.com/lumina-tl/lumina)

BlueTL uses PySide6, OpenAI's Python client, python-docx, Pillow, Manga OCR,
OpenCV, PyTorch/torchvision, psd-tools, rarfile, py7zr, and the vendored comic-text-detector.
Their respective licenses remain applicable. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

The BlueTL application code is released under the MIT License. The vendored
`comic_text_detector\` component is GPL-3.0; distributed builds containing it must comply
with GPL-3.0 and provide the complete corresponding source. See [LICENSE.md](LICENSE.md).

---

*BlueTL · Version v0.1.5 · Author: Blue-Wingz @ facedesk · Published by borneanwingz.fl*

