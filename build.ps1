$ErrorActionPreference = 'Stop'
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -r requirements.txt
$icon = Join-Path $PSScriptRoot 'assets\bluetl.ico'
if (!(Test-Path $icon)) { throw "Missing icon: $icon" }
$ocrModel = Join-Path $PSScriptRoot 'assets\manga-ocr-model'
if (!(Test-Path (Join-Path $ocrModel 'vocab.txt'))) { throw "Missing Manga OCR model: $ocrModel" }
# //remarks: Manga OCR's Japanese tokenizer (transformers bert_japanese -> MeCab) imports
# //remarks: unidic_lite at runtime and reads its ~260 MB dictionary from unidic_lite\dicdir.
# //remarks: PyInstaller has no hook for unidic_lite, so it bundled the Python module but
# //remarks: dropped dicdir, which caused "Unable to load vocabulary from file" in the EXE.
# //remarks: --collect-data unidic_lite forces the full dictionary (version, sys.dic, etc.)
# //remarks: into the bundle so frozen builds tokenize Japanese exactly like source runs.
# //remarks: --collect-data manga_ocr bundles manga_ocr\assets\example.jpg, which MangaOcr
# //remarks: opens in __init__ and which PyInstaller otherwise omits.
py -3.12 -m PyInstaller --noconfirm --clean --windowed --noupx --hidden-import unicodedata --collect-data unidic_lite --collect-data manga_ocr --icon $icon --add-data "$icon;assets" --add-data "$ocrModel;assets\manga-ocr-model" --name BlueTL app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
# //remarks: Fail the build loudly if the unidic dictionary data is missing, so a broken
# //remarks: OCR bundle can never be shipped again (this was the cause of the OCR failure).
$unidicData = Join-Path $PSScriptRoot 'dist\BlueTL\_internal\unidic_lite\dicdir\version'
if (!(Test-Path $unidicData)) { throw "unidic_lite dictionary was not bundled: $unidicData" }
Write-Host "Built: dist\BlueTL\BlueTL.exe"
