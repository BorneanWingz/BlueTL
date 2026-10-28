# BlueTL

Windows PySide6 manga translation desktop app using any OpenAI-compatible API provider.

## Run from source

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Enter the provider's OpenAI-compatible **Base URL**, API key, model, and target language in the app. The configured platform base URL is `https://serveras.click/v1`. These settings are restored on the next startup. The API key is protected with Windows DPAPI and stored in the per-user config file; it is never written as plaintext. Models whose IDs begin with `asai/freemodel-` are prioritized before paid/non-free models. If a non-free model is selected, free models are still attempted first, then the selected model, then other non-free fallbacks. Click **Translate all**: OCR runs automatically for imported images, then every row is translated.

## Build the executable

Run in PowerShell from this folder:

```powershell
.\build.ps1
```

The executable is created at `dist\BlueTL\BlueTL.exe`. The About tab identifies version `v1.0`, publisher `borneanwingz.fl`, and author `Blue-Wingz @ facedesk`. The build is not digitally signed unless a trusted Windows code-signing certificate is supplied; PyInstaller does not create a trusted signature by itself.

## Current scope

The app imports JPG, JPEG, PNG, and WebP images, plus ZIP archives and RAR archives containing those images. The order files were selected in is ignored: imported images are ordered by file name using natural numeric order (`chapter-2.jpg` before `chapter-10.jpg`), and images extracted from an archive keep that same name order, so page numbers always follow the file names. It automatically runs Manga OCR when **Translate all** is clicked, provides editable page/panel/OCR rows, translates every row through the configured OpenAI-compatible API with model fallbacks, and exports TXT/DOCX. The executable uses `assets\bluetl.ico` as its icon. Manga OCR returns page-level text in this first integration; region detection, vertical/horizontal region splitting, and automatic panel assignment remain future improvements. No provider-specific endpoint, model, or API key is hardcoded.

The first OCR run may download Manga OCR model files during setup and can require substantial disk space. Run it with internet access once, then the downloaded OCR model is used locally. Translation through `https://serveras.click/v1` is remote API inference and still requires internet access each time. The API's model names do not provide downloadable model weights; the provider would need to publish compatible weights or a local server package before those models could run offline. Do not attempt to scrape or download model data from the API.
