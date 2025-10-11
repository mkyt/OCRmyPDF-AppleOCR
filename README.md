# OCRmyPDF AppleOCR

This is a plugin for [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF/) that enables OCR using the Apple Vision Framework on macOS.

## Installation

```bash
pip install ocrmypdf-appleocr
```

## Usage

```bash
ocrmypdf --plugin ocrmypdf_appleocr input.pdf output.pdf

ocrmypdf --pdf-renderer=hocr --optimize 2 --plugin ocrmypdf_appleocr --appleocr-lang=jpn input.pdf output.pdf
```

Note that only [`hocr` renderer](https://ocrmypdf.readthedocs.io/en/latest/advanced.html#changing-the-pdf-renderer), which is default in the latest version of OCRmyPDF, is supported for this plugin.


## Options

- `--appleocr-lang`: Language(s) for Apple Vision OCR (default: None, which means auto-detect). You can specify multiple languages separated by commas (e.g., `jpn,eng`).
- `--appleocr-disable-correction`: Disable language correction in Apple Vision OCR (default: False)
- `--appleocr-recognition-level`: Recognition level for Apple Vision OCR (default: accurate). Choices are `fast` and `accurate`.

If you do not specify `--appleocr-lang` or specify multiple languages, the plugin will attempt to detect the language using the `langdetect` library. Note that the accuracy of language detection may vary depending on the content of the document.