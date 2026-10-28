# Third-party notices

BlueTL was informed by the architecture and documentation of these MIT-licensed projects:

- KŌMA Studio: https://git.mitgai.net/klaus-2/koma-studio
- manga-translation: https://github.com/M3MONs/manga-translation
- Lumina: https://github.com/lumina-tl/lumina

Their repositories were cloned under `references/` for local inspection. BlueTL does not bundle their source code. The reusable design ideas applied here are an editable pipeline, sequential local OCR, per-page structured records, and a translation-provider boundary.

Model weights and fonts used by those projects are not automatically covered by their source-code MIT licenses. Any future BlueTL model download must preserve the model's own license and attribution requirements. In particular, NLLB-200 models may be CC-BY-NC 4.0 and therefore unsuitable for commercial use.

Current BlueTL dependencies are installed from PyPI and retain their respective licenses. Manga OCR model files are downloaded by the Manga OCR package at runtime/setup and are not included in this repository.
