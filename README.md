# OCRmyPDF AppleOCR

A plugin for [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF/) that enables optical character recognition (OCR) using the text detection capabilities of Apple’s [Vision Framework](https://developer.apple.com/documentation/vision) on macOS.

Apple’s proprietary OCR implementation provides excellent accuracy and speed compared to other on-device OCR engines such as Tesseract.

## Installation

Requires macOS, Python 3.11 or later, and OCRmyPDF 14.2.1 or later (17 or later for the `--ocr-engine` and `fpdf2` renderer features described below).

The package is available on [PyPI](https://pypi.org/project/ocrmypdf-appleocr/).

```bash
pip install ocrmypdf-appleocr
```

## Usage

The plugin registers itself as an OCRmyPDF entry point, so it is loaded automatically once installed — no `--plugin` option is required. Specify the language(s) for OCR using the `-l` or `--language` option. If you want to enable automatic language detection in `accurate` or `fast` mode, use `und` (undetermined) as the language code.

```bash
ocrmypdf -l jpn input.pdf output.pdf
```

Because the plugin is loaded automatically, it takes over as the OCR engine whenever `--ocr-engine` is left at its default (`auto`). To select it explicitly, or to go back to Tesseract without uninstalling the plugin:

```bash
ocrmypdf --ocr-engine appleocr -l jpn input.pdf output.pdf
ocrmypdf --ocr-engine tesseract -l jpn input.pdf output.pdf
```

**If you have other third-party OCR engine plugins installed, always pass `--ocr-engine` explicitly.** With built-in Tesseract alone, `auto` reliably resolves to this plugin, because an entry-point plugin is registered after the built-ins and OCRmyPDF's `get_ocr_engine` hook takes the first result in reverse registration order. Once a second third-party engine plugin is installed, however, both claim `auto`, and which one wins comes down to the order Python happens to discover their entry points — not something you can control or should rely on. Naming the engine removes the ambiguity: every well-behaved engine plugin declines when `--ocr-engine` names a different engine.

Loading the plugin explicitly with `--plugin ocrmypdf_appleocr` still works, and is what you need on OCRmyPDF versions older than 17, which have no `--ocr-engine` option.

## Options

- `--appleocr-recognition-mode`: Recognition mode for Apple Vision OCR. Choices: `fast`, `accurate`, or `livetext`. Default: `livetext` on macOS 13 and later, `accurate` on macOS 12 and earlier.
- `--appleocr-disable-correction`: Disable language correction in Apple Vision OCR (default: `False`)
- `--ocr-engine`: OCR engine to use. The plugin appends `appleocr` to OCRmyPDF's built-in choices (`auto`, `tesseract`, `none`). Default: `auto`, which resolves to this plugin when it is the only engine plugin installed; specify `appleocr` explicitly if other third-party engine plugins are also present. Requires OCRmyPDF 17 or later.
- `--pdf-renderer`: Renderer used to embed OCR results as invisible (“phantom”) text. Choices: `sandwich`, `fpdf2` (also `auto`, `hocr`, `hocrdebug`, which OCRmyPDF now treats as aliases for `fpdf2`). Default: `sandwich`.
- `-l` or `--language`: Specify OCR language(s) in ISO 639-2 three-letter codes. Use `und` for undetermined language. Specifying multiple languages joined with `+` (e.g. `eng+fra`) for multilingual documents is **not supported**.

Automatic language detection (`und`) is **not supported** in `livetext` mode. `und` is also only accepted as the *sole* language: combining it with other language codes (e.g. `-l und -l eng`) is an error — use specific language codes instead.

### Recognition Modes

The `fast` and `accurate` modes use [VNRecognizeTextRequest](https://developer.apple.com/documentation/vision/vnrecognizetextrequest?language=objc) from Apple's Vision framework.

The `livetext` mode uses the newer [ImageAnalyzer](https://developer.apple.com/documentation/visionkit/imageanalyzer) API from the VisionKit framework.
Although officially Swift-only, it can be accessed via private API (`VKCImageAnalyzer`) through `pyobjc`.

The key difference is that LiveText supports **vertical text layout in East Asian languages**, which is not handled properly by the older API.

### PDF Renderers

This plugin supports two [OCRmyPDF renderers](https://ocrmypdf.readthedocs.io/en/latest/advanced.html#changing-the-pdf-renderer): `sandwich` and `fpdf2`. **`sandwich` is the recommended renderer and the plugin's default**, because OCRmyPDF's built-in `fpdf2` renderer currently places the invisible text layer incorrectly for both rotated and vertical text (see the known limitations below).

- **sandwich:**
  The plugin renders OCR output as a PDF layer with invisible text (via its own [`generate_pdf()`](ocrmypdf_appleocr/pdf.py)), which OCRmyPDF then merges with the original page image. The plugin builds the PDF text matrix itself from the full quadrilateral Apple Vision reports, so rotation, text extent and font size stay correct on skewed and rotated pages, and vertical (top-to-bottom) text layout in CJK scripts is handled explicitly.
- **fpdf2:**
  The plugin returns OCR output as an [`OcrElement`](https://ocrmypdf.readthedocs.io/en/latest/plugins.html#ocr-engine) tree via the newer `generate_ocr()` plugin API (OCRmyPDF 17+), and OCRmyPDF's built-in fpdf2-based renderer converts it to PDF. This replaces the legacy `hocr` renderer, which OCRmyPDF now treats as an alias for `fpdf2`.

  **Known limitations of the `fpdf2` renderer (as of OCRmyPDF 17.8.1).** Both are upstream OCRmyPDF bugs, not specific to this plugin, and both affect only the invisible text layer — the extracted text itself is still correct, but on-screen text selection and highlighting are not:

  - **Rotated text gets an oversized bounding box and font size.** An `OcrElement` bbox is axis-aligned by the hOCR convention, so a rotated line can only be described by the axis-aligned bounding box of its quadrilateral ([`_aabb()`](ocrmypdf_appleocr/ocr_tree.py)) plus a separate `textangle`. The renderer tries to recover the true line box by un-rotating that bbox, but un-rotating an axis-aligned box and taking its bounding box again inflates it instead of recovering the original quad, and the font size is derived from that inflated height. The error grows with the rotation angle: on the ~8°-rotated `script/examples/eng_rot1.pdf`, `fpdf2` emits a ~147 pt font where `sandwich` uses ~15 pt, while on the unrotated `script/examples/eng.pdf` the two agree (~14.5 pt).
  - **Vertical (tategaki) CJK text is mis-positioned.** The text box for each vertical line collapses into a narrow horizontal band instead of spanning the column.

If `--pdf-renderer` is left at its default (`auto`), the plugin defaults to `sandwich`. Pass `--pdf-renderer sandwich` or `--pdf-renderer fpdf2` explicitly to override this.

### Supported Languages

As of macOS Tahoe 26, the following languages are supported by Apple Vision OCR:

|   Language code  |   Language name            |   Fast mode  |   Accurate mode  |   LiveText  |
|------------------|----------------------------|--------------|------------------|-------------|
|   eng            |   English                  |   ✓          |   ✓              |   ✓         |
|   fra            |   French                   |   ✓          |   ✓              |   ✓         |
|   ita            |   Italian                  |   ✓          |   ✓              |   ✓         |
|   deu            |   German                   |   ✓          |   ✓              |   ✓         |
|   spa            |   Spanish                  |   ✓          |   ✓              |   ✓         |
|   por            |   Portuguese               |   ✓          |   ✓              |   ✓         |
|   chi_sim        |   Chinese (Simplified)     |              |   ✓              |   ✓         |
|   chi_tra        |   Chinese (Traditional)    |              |   ✓              |   ✓         |
|   yue_sim        |   Cantonese (Simplified)   |              |   ✓              |   ✓         |
|   yue_tra        |   Cantonese (Traditional)  |              |   ✓              |   ✓         |
|   kor            |   Korean                   |              |   ✓              |   ✓         |
|   jpn            |   Japanese                 |              |   ✓              |   ✓         |
|   rus            |   Russian                  |              |   ✓              |   ✓         |
|   ukr            |   Ukrainian                |              |   ✓              |   ✓         |
|   tha            |   Thai                     |              |   ✓              |   ✓         |
|   vie            |   Vietnamese               |              |   ✓              |   ✓         |
|   ara            |   Arabic                   |              |   ✓              |   ✓         |
|   ars            |   Arabic (Najdi)           |              |   ✓              |   ✓         |
|   tur            |   Turkish                  |              |   ✓              |   ✓         |
|   ind            |   Indonesian               |              |   ✓              |   ✓         |
|   ces            |   Czech                    |              |   ✓              |   ✓         |
|   dan            |   Danish                   |              |   ✓              |   ✓         |
|   nld            |   Dutch                    |              |   ✓              |   ✓         |
|   nor            |   Norwegian                |              |   ✓              |   ✓         |
|   nno            |   Norwegian (Nynorsk)      |              |   ✓              |   ✓         |
|   nob            |   Norwegian (Bokmål)       |              |   ✓              |   ✓         |
|   msa            |   Malay                    |              |   ✓              |   ✓         |
|   pol            |   Polish                   |              |   ✓              |   ✓         |
|   ron            |   Romanian                 |              |   ✓              |   ✓         |
|   swe            |   Swedish                  |              |   ✓              |   ✓         |


## Acknowledgements

This project incorporates and references code from the following projects:

- [straussmaximilian/ocrmac](https://github.com/straussmaximilian/ocrmac) - for invoking `VKCImageAnalyzer` (LiveText API) via `pyobjc`
- [ocrmypdf/OCRmyPDF-EasyOCR](https://github.com/ocrmypdf/OCRmyPDF-EasyOCR) - for PDF rendering of recognized text
