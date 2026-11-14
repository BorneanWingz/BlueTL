# Third-party notices

BlueTL was informed by the architecture and documentation of these MIT-licensed projects:

- KŌMA Studio: https://git.mitgai.net/klaus-2/koma-studio
- manga-translation: https://github.com/M3MONs/manga-translation
- Lumina: https://github.com/lumina-tl/lumina

Their repositories were cloned under `references/` for local inspection. BlueTL does not bundle their source code. The reusable design ideas applied here are an editable pipeline, sequential local OCR, per-page structured records, and a translation-provider boundary.

Model weights and fonts used by those projects are not automatically covered by their source-code MIT licenses. Any future BlueTL model download must preserve the model's own license and attribution requirements. In particular, NLLB-200 models may be CC-BY-NC 4.0 and therefore unsuitable for commercial use.

Current BlueTL dependencies are installed from PyPI and retain their respective licenses, with one exception: comic-text-detector is vendored in `comic_text_detector/` under GPL-3.0, as described below. Manga OCR model files are downloaded by the Manga OCR package at runtime/setup and are not included in this repository; the comic-text-detector weights are downloaded once from the URL below and are likewise not committed.

## Bundled third-party code: comic-text-detector

BlueTL performs manga text detection with **comic-text-detector**, vendored verbatim in
`comic_text_detector/` from kha-white's fork at the revision mokuro pins as its submodule:

- https://github.com/kha-white/comic-text-detector (GPL-3.0)
- https://github.com/dmMaze/comic-text-detector (upstream, GPL-3.0)

The upstream `LICENSE` is kept at `comic_text_detector/LICENSE`, and `comic_text_detector/VENDOR.md`
lists exactly which upstream files were copied and which training-only files were left out. No file
in that folder has been modified.

Because this component is GPL-3.0, **any distributed BlueTL build that includes it must comply with
GPL-3.0**: recipients must receive the complete corresponding source of the combined work (BlueTL's
source together with `comic_text_detector/`) under GPL-3.0, and the build must not be relicensed
under incompatible or closed-source terms. Builds that exclude this component are not affected.

### Text detection weights

`comictextdetector.pt` is not committed to this repository (see `.gitignore`) and is downloaded once
from the manga-image-translator project's release `beta-0.2.1`:

- https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.2.1/comictextdetector.pt

manga-image-translator is GPL-3.0 and the release page states no separate license for the weights, so
they are treated as covered by that project's terms. The upstream README documents that the detector
was trained on Manga109-s (© the individual authors), DCM and synthetic data; that notice is carried
over here. BlueTL bundles no training data or fonts.
## Archive libraries

7Z archives are read with **py7zr** (LGPL-2.1-or-later), an unmodified dependency installed from PyPI; it also pulls in pybcj and pyppmd as its codec backends. RAR archives are read with **rarfile** (ISC), which requires an external unrar or WinRAR binary supplied by the user. ZIP archives use the Python standard library.
