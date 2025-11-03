# OCRmyPDF AppleOCR

A plugin for [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF/) that enables optical character recognition (OCR) using the text detection capabilities of Apple’s [Vision Framework](https://developer.apple.com/documentation/vision) on macOS.

Apple’s proprietary OCR implementation provides excellent accuracy and speed compared to other on-device OCR engines such as Tesseract.

## Installation

The package is available on [PyPI](https://pypi.org/project/ocrmypdf-appleocr/).

```bash
pip install ocrmypdf-appleocr
```

## Usage

To use the plugin, pass the `--plugin` option when invoking `ocrmypdf`. You can also specify the language(s) for OCR using the `-l` or `--language` option. If you want to enable automatic language detection, use `und` (undetermined) as the language code.

```bash
ocrmypdf -l jpn --plugin ocrmypdf_appleocr input.pdf output.pdf
```

## Options

- `--appleocr-recognition-mode`: Recognition mode for Apple Vision OCR. Choices: `fast`, `accurate`, or `livetext`. Default: `livetext` on macOS 13 and later, `accurate` on macOS 12 and earlier.
- `--appleocr-disable-correction`: Disable language correction in Apple Vision OCR (default: `False`)
- `--pdf-renderer`: Renderer used to embed OCR results as invisible (“phantom”) text. Choices: `hocr`, `sandwich`. Default: `sandwich`.
- `-l` or `--language`: Specify OCR language(s) in ISO 639-2 three-letter codes. Use `und` for undetermined language. Specifying multiple languages joined with `+` (e.g. `eng+fra`) for multilingual documents is **not supported**.

Automatic language detection (`und`) is **not supported** in `livetext` mode.

### Recognition Modes

The `fast` and `accurate` modes use [VNRecognizeTextRequest](https://developer.apple.com/documentation/vision/vnrecognizetextrequest?language=objc) from Apple's Vision framework.

The `livetext` mode uses the newer [ImageAnalyzer](https://developer.apple.com/documentation/visionkit/imageanalyzer) API from the VisionKit framework.
Although officially Swift-only, it can be accessed via private API (`VKCImageAnalyzer`) through `pyobjc`.

The key difference is that LiveText supports **vertical text layout in East Asian languages**, which is not handled properly by the older API.

### PDF Renderers

This plugin supports two [OCRmyPDF renderers](https://ocrmypdf.readthedocs.io/en/latest/advanced.html#changing-the-pdf-renderer): `hocr` and `sandwich`.
The default is `sandwich`.

- **sandwich:**
  The plugin renders OCR output as a PDF layer with invisible text, which OCRmyPDF then merges with the original page image.
- **hocr:**
  The plugin outputs OCR results as [hOCR markup](https://kba.github.io/hocr-spec/1.2/), and OCRmyPDF converts the markup to PDF.

Because the hOCR format cannot represent vertical text in East Asian (CJK) scripts, the `hocr` renderer cannot accurately reproduce vertical text layouts.
However, OCRmyPDF’s built-in hOCR-to-PDF conversion is more mature and may perform better in other scenarios.

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
