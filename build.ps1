$ErrorActionPreference = 'Stop'
py -3.14 -m pip install --upgrade pip
py -3.14 -m pip install -r requirements.txt
$icon = Join-Path $PSScriptRoot 'assets\bluetl.png'
if (!(Test-Path $icon)) { throw "Missing icon: $icon" }
$versionInfo = Join-Path $PSScriptRoot 'version_info.txt'
if (!(Test-Path $versionInfo)) { throw "Missing Windows version information: $versionInfo" }
$ocrModel = Join-Path $PSScriptRoot 'assets\manga-ocr-model'
if (!(Test-Path (Join-Path $ocrModel 'vocab.txt'))) { throw "Missing Manga OCR model: $ocrModel" }
# //remarks: Text detection runs on the vendored comic_text_detector package (see its VENDOR.md), so a
# //remarks: missing package or missing weights must fail the build here instead of at the end user's page.
$ctdPackage = Join-Path $PSScriptRoot 'comic_text_detector\inference.py'
if (!(Test-Path $ctdPackage)) { throw "Missing vendored text detector package: $ctdPackage" }
# //remarks: The weights are not committed (see .gitignore). Download comictextdetector.pt once from
# //remarks: https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.2.1/comictextdetector.pt
# //remarks: and place it in assets\comic-text-detector-model, exactly like the Manga OCR model folder.
$ctdModel = Join-Path $PSScriptRoot 'assets\comic-text-detector-model'
if (!(Test-Path (Join-Path $ctdModel 'comictextdetector.pt'))) { throw "Missing text detection model: $ctdModel" }
# //remarks: Manga OCR's Japanese tokenizer (transformers bert_japanese -> MeCab) imports
# //remarks: unidic_lite at runtime and reads its ~260 MB dictionary from unidic_lite\dicdir.
# //remarks: PyInstaller has no hook for unidic_lite, so it bundled the Python module but
# //remarks: dropped dicdir, which caused "Unable to load vocabulary from file" in the EXE.
# //remarks: --collect-data unidic_lite forces the full dictionary (version, sys.dic, etc.)
# //remarks: into the bundle so frozen builds tokenize Japanese exactly like source runs.
# //remarks: --collect-data manga_ocr bundles manga_ocr\assets\example.jpg, which MangaOcr
# //remarks: opens in __init__ and which PyInstaller otherwise omits.
# //remarks: --collect-submodules comic_text_detector bundles the vendored detector package: app.py
# //remarks: imports it lazily inside a function, so static analysis alone can miss its submodules.
# //remarks: --collect-all transformers is required because transformers 5.x resolves classes such as
# //remarks: ViTImageProcessor through lazy imports, which PyInstaller's static analysis cannot see.
# //remarks: Without it, the frozen build raised "cannot find ViTImageProcessor" on every OCR run.
# //remarks: --collect-all torchvision forces the compiled _C_stable/image_stable extensions into the
# //remarks: bundle; the stock hook expects torchvision._C and silently dropped this wheel's .pyd files.
# //remarks: --collect-submodules psd_tools bundles the PSD compositing helpers: app.py imports psd_tools lazily
# //remarks: inside flatten_psd, so static analysis alone would miss its compression/adjustment submodules and
# //remarks: a .psd page would then fail to flatten inside the frozen EXE.
# //remarks: --collect-all py7zr bundles the 7z reader the same way: app.py imports py7zr lazily inside the
# //remarks: archive branch of expand_inputs, and without this the frozen EXE silently lost 7z support (the
# //remarks: package appeared only as a "delayed" import in warn-BlueTL.txt). It also pulls in the pybcj,
# //remarks: pyppmd and inflate64 codec backends that py7zr loads at run time.
py -3.14 -m PyInstaller --noconfirm --clean --windowed --noupx --hidden-import unicodedata --collect-data unidic_lite --collect-data manga_ocr --collect-submodules comic_text_detector --collect-all psd_tools --collect-all py7zr --collect-all transformers --collect-all torchvision --icon $icon --version-file $versionInfo --add-data "$icon;assets" --add-data "$ocrModel;assets\manga-ocr-model" --add-data "$ctdModel;assets\comic-text-detector-model" --name BlueTL app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
# //remarks: Fail the build loudly if the unidic dictionary data is missing, so a broken
# //remarks: OCR bundle can never be shipped again (this was the cause of the OCR failure).
$unidicData = Join-Path $PSScriptRoot 'dist\BlueTL\_internal\unidic_lite\dicdir\version'
if (!(Test-Path $unidicData)) { throw "unidic_lite dictionary was not bundled: $unidicData" }
# //remarks: Same loud failure for the detector weights: a build without them would report "no text" on
# //remarks: every page at run time, which is far harder to diagnose than a failed build.
$ctdData = Join-Path $PSScriptRoot 'dist\BlueTL\_internal\assets\comic-text-detector-model\comictextdetector.pt'
if (!(Test-Path $ctdData)) { throw "Text detection model was not bundled: $ctdData" }
# //remarks: transformers 5.x exposes ViTImageProcessor through lazy imports; if its module tree was
# //remarks: not collected, OCR fails at run time with "cannot find ViTImageProcessor".
$vit = Join-Path $PSScriptRoot 'dist\BlueTL\_internal\transformers\models\vit\image_processing_vit.py'
if (!(Test-Path $vit)) { throw "transformers image processing modules were not bundled (ViTImageProcessor would be missing): $vit" }
# //remarks: torchvision must keep its compiled extensions; Manga OCR's processor falls back to a slow
# //remarks: PIL backend without them and detector preprocessing fails outright if they are absent.
$tvC = Get-ChildItem (Join-Path $PSScriptRoot 'dist\BlueTL\_internal\torchvision') -Recurse -Filter '*.pyd' -ErrorAction SilentlyContinue
if (!$tvC) { throw "torchvision compiled extensions were not bundled (torchvision._C missing)" }
# //remarks: 7z support is a lazy import, so a build can succeed while quietly dropping it. Fail here instead
# //remarks: of at the user's first .7z import, exactly like the unidic and detector checks above.
$sevenZip = Join-Path $PSScriptRoot 'dist\BlueTL\_internal\py7zr\__init__.py'
if (!(Test-Path $sevenZip)) { throw "py7zr was not bundled (7z import would fail at run time): $sevenZip" }
Write-Host "Built: dist\BlueTL\BlueTL.exe"
