# Vendored: comic_text_detector (kha-white/comic-text-detector)

BlueTL detects manga text with the model and inference code of kha-white's fork of
dmMaze/comic-text-detector - the detector [mokuro](https://github.com/kha-white/mokuro) uses.
It is vendored here because the project is not published on PyPI and carries no packaging
metadata, so it cannot be installed with `pip`; mokuro keeps the same code as a git submodule.

- Source: https://github.com/kha-white/comic-text-detector (fork of
  https://github.com/dmMaze/comic-text-detector)
- Revision: `92ea867bd85a13105ebcf6bb7f7314784ca89902`, the revision mokuro pins as its
  `comic_text_detector` submodule
- License: GNU General Public License v3.0 - see `LICENSE` in this folder

## Included files

Only the runtime closure of `comic_text_detector.inference.TextDetector` is copied, keeping the
flat layout of the upstream repository so the upstream imports such as
`from comic_text_detector.utils.textblock import TextBlock` keep working unmodified:

- `inference.py`, `basemodel.py`
- `models/yolov5/` (the YOLOv5 text block detector)
- `utils/db_utils.py`, `utils/imgproc_utils.py`, `utils/io_utils.py`, `utils/textblock.py`,
  `utils/textmask.py`, `utils/weight_init.py`, `utils/yolov5_utils.py`
- `LICENSE`

Upstream training and data-generation files (`train_db.py`, `train_seg.py`, `db_dataset.py`,
`seg_dataset.py`, `text_rendering.py`, `utils/general.py`, `utils/export.py`, `utils/loss.py`
and `data/`) are not copied: they pull in training-only dependencies and are never imported by
`TextDetector`. No file in this folder has been modified.

## Model weights

The weights are not committed to this repository (see `.gitignore`). Download
`comictextdetector.pt` once and place it at
`assets/comic-text-detector-model/comictextdetector.pt`:

```
https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.2.1/comictextdetector.pt
```

This is the release mokuro downloads its weights from, and the same URL is documented in
`build.ps1`, which fails the build when the file is missing. The weights are published by the
manga-image-translator project (GPL-3.0), whose README describes the training data (Manga109-s,
DCM and synthetic data); that notice is preserved in `THIRD_PARTY_NOTICES.md`.

## Runtime dependencies

`comic_text_detector` imports `cv2`, `torch`, `torchvision`, `numpy`, `pyclipper`, `shapely`,
`tqdm` and `torchsummary`. They are declared in `requirements.txt`; `torch` already arrives with
Manga OCR, and `opencv-python-headless` is used instead of `opencv-python` so that the frozen
build does not pull a second copy of the Qt libraries next to PySide6.

## License consequences

`comic_text_detector` is GPL-3.0. Any distributed BlueTL build that includes it must be
distributed under GPL-3.0 terms, with the complete corresponding source of the combined work
(including this folder) available to recipients. See `THIRD_PARTY_NOTICES.md`.
