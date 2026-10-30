# BlueTL

Windows PySide6 manga translation desktop app using any OpenAI-compatible API provider.

## Run from source

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Enter the provider's OpenAI-compatible **Base URL**, API key, model, and target language in the app. The configured platform base URL is `https://serveras.click/v1`. These settings are restored on the next startup. The API key is protected with Windows DPAPI and stored in the per-user config file; it is never written as plaintext. Models whose IDs begin with `asai/freemodel-` are prioritized before paid/non-free models. If a non-free model is selected, free models are still attempted first, then the selected model, then other non-free fallbacks. Click **Translate all** to recognise and translate in one step. Click **Recognize OCR** first when you want to run the local OCR on its own and review or correct the recognized lines before any API tokens are spent; **Translate all** then reuses those rows instead of recognizing again. Only rows without a translation are sent to the API. Importing a new selection clears the previous batch's rows. **Add row** is enabled after recognition and inserts an empty row below the selected line for manual text entry; **Delete row** removes the selected line so invented noise can be cleared. The import dialog reopens in the folder used by the previous import. Clear a Translation cell to have that row translated again.

## Build the executable

Run in PowerShell from this folder:

```powershell
.\build.ps1
```

The executable is created at `dist\BlueTL\BlueTL.exe`. The build requires `assets\bluetl.ico`, `assets\manga-ocr-model`, `assets\comic-text-detector-model\comictextdetector.pt` and the vendored `comic_text_detector\` package, and fails with a clear error when one of them is missing. The bundled detector is GPL-3.0, so check `THIRD_PARTY_NOTICES.md` before distributing a build. The About tab identifies version `v1.0`, publisher `borneanwingz.fl`, and author `Blue-Wingz @ facedesk`. The build is not digitally signed unless a trusted Windows code-signing certificate is supplied; PyInstaller does not create a trusted signature by itself.

## Current scope

The app imports JPG, JPEG, PNG, and WebP images, plus ZIP archives and RAR archives containing those images. The order files were selected in is ignored: imported images are ordered by file name using natural numeric order (`chapter-2.jpg` before `chapter-10.jpg`), and images extracted from an archive keep that same name order, so page numbers always follow the file names. **Recognize OCR** runs Manga OCR locally and loads editable page/panel/OCR rows without calling the translation API; it is optional, because **Translate all** runs the same local OCR automatically when no rows have been recognized yet. **Translate all** sends only rows without a translation through the configured OpenAI-compatible API with model fallbacks and exports TXT/DOCX. After recognition, **Add row** inserts an editable row below the selected line and **Delete row** removes the selected line, so noise lines can be cleared. Each OCR row keeps its source crop. All actions (Import, Recognize OCR, Add row, Delete row, Translate all, Test API, Export TXT, Export DOCX) sit in a single row of compact buttons whose labels wrap instead of being clipped. Rows with independent suspicion checks are marked `CHECK` and are held back from translation until reviewed and approved by clearing the marker. The folder of the last import is remembered and reopened by the next import dialog. A new import clears the previous batch's OCR and translation rows. The executable uses `assets\bluetl.ico` as its icon. Text detection is done by kha-white's comic-text-detector, the detector mokuro uses; it is vendored under `comic_text_detector\` and loaded from `assets\comic-text-detector-model\comictextdetector.pt`. Manga OCR is then called only on the detected text blocks; if no block is detected, the page is reported as having no text rather than sending a whole page to the model, which can hallucinate text on blank input. The linked GLM-OCR-Manga-LoRA is a separate generative vision-language LoRA adapter over `zai-org/GLM-OCR`; it is not enabled by default because it requires the much larger GLM-OCR base model and also does not provide a detector or confidence score. Damaged images are reported and skipped so the rest of the batch can continue. Recognized rows receive sequential panel numbers, and manually inserted rows are placed below the selected line with later rows renumbered on that page. No provider-specific endpoint, model, or API key is hardcoded.

Both OCR stages are local and read their weights from the bundle: Manga OCR from `assets\manga-ocr-model` and text detection from `assets\comic-text-detector-model\comictextdetector.pt` (about 520 MB together). The detector weights are a one-time download from the manga-image-translator release `beta-0.2.1` and, like the `kha-white/manga-ocr-base` weights, the file must already be in place before OCR can run - a missing or truncated file is reported in the OCR error dialog together with its exact path. Detection takes a few seconds per page on CPU, so the first page of a batch also pays the one-off detector load time. Translation through `https://serveras.click/v1` is remote API inference and still requires internet access each time. The API's model names do not provide downloadable model weights; the provider would need to publish compatible weights or a local server package before those models could run offline. Do not attempt to scrape or download model data from the API.
