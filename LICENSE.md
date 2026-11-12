# License

BlueTL is free and open-source software. This file explains, in plain words, what
you are allowed to do with it and what you must do if you share it.

> **The short version:** you may use, copy, change and share BlueTL — including for
> commercial purposes — as long as you keep the copyright notice and this licence with
> it. The software is provided "as is", without any warranty. **One exception applies:**
> the bundled comic-text-detector component carries the GPL-3.0 licence, and a
> distributed build that includes it must be shared under GPL-3.0 terms with its
> complete corresponding source.

The formal terms are below. They are the standard **MIT License**, applied to the
BlueTL application code (everything outside the `comic_text_detector/` folder).

---

## MIT License

Copyright (c) 2026 Blue-Wingz (borneanwingz.fl)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## How the project is put together (licensing)

BlueTL is a permissive-licensed application with one strongly copyleft bundled
component. The split is deliberate and is the same shape as the app itself:

- Everything written for BlueTL — `app.py`, the build script, the packaging
  configuration, the model-loading glue — is MIT-licensed.
- The manga **text detector** is vendored verbatim from kha-white's
  comic-text-detector, which is GPL-3.0. It lives in its own `comic_text_detector/`
  folder with its upstream `LICENSE` kept in place and no file modified.
- Any distributed BlueTL build that includes `comic_text_detector/` therefore must
  comply with **GPL-3.0**: recipients must receive the complete corresponding source
  of the combined work (BlueTL's source together with that folder) under GPL-3.0, and
  the build must not be relicensed under incompatible or closed-source terms.
- Builds that exclude this component are not affected by this clause and remain
  purely MIT.

### Component map

| Capability | Component | License |
| --- | --- | --- |
| Desktop interface | PySide6 (Qt for Python) | LGPL-3.0 |
| OpenAI-compatible API client | `openai` Python client | MIT |
| DOCX export | python-docx | MIT |
| Image loading and compositing | Pillow | MIT-CMU |
| Layered PSD flattening | psd-tools | MIT |
| Manga OCR (Japanese text recognition) | manga-ocr (kha-white/manga-ocr-base) | Apache-2.0 |
| Image processing | OpenCV (`opencv-python-headless`) | Apache-2.0 |
| Geometry (text-block polygons) | pyclipper, shapely | MIT |
| Deep learning runtime | PyTorch / torchvision | BSD-3 |
| Archive reading | rarfile | ISC |
| Japanese tokenizer data | unidic_lite (bundled with the build) | BSD-3 / GPL/LGPL (MeCab dictionary components) |
| Text-block detection | comic-text-detector (vendored in `comic_text_detector/`) | GPL-3.0 |

### A note on the bundled parts

- The **core** of BlueTL is built only from components with permissive licences
  (MIT, Apache-2.0, BSD, MIT-CMU, ISC, LGPL-3.0). PySide6 is LGPL-3.0, which allows
  proprietary use as long as Qt's own terms are honoured for the Qt parts themselves;
  it does not impose its terms on the rest of BlueTL.
- The **vendored comic-text-detector** is the one GPL-3.0 component. Because it is
  statically bundled into the distributed executable, the whole distributed build
  must be treated as a GPL-3.0 combined work. Keep the upstream `LICENSE` file in
  `comic_text_detector/` intact and provide the corresponding source to recipients.
- **Model weights** are not committed to this repository. The Manga OCR weights
  (`kha-white/manga-ocr-base`, Apache-2.0) are downloaded by the `manga-ocr` package,
  and the text-detection weights (`comictextdetector.pt`) are downloaded once from the
  manga-image-translator release `beta-0.2.1`. The manga-image-translator project is
  GPL-3.0 and its release page states no separate licence for the weights, so they are
  treated as covered by that project's terms; the upstream README documents the
  training data (Manga109-s © the individual authors, DCM and synthetic data), and
  that notice is carried in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- **Fonts** bundled with a build must carry their own licence terms; BlueTL bundles no
  fonts in the repository.

This summary is provided to help you understand the licences at a glance. If anything
here conflicts with the full licence texts of the components listed above, those full
texts take precedence.

---

*See also: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the detailed third-party
notices and the vendoring record in [`comic_text_detector/VENDOR.md`](comic_text_detector/VENDOR.md).*
