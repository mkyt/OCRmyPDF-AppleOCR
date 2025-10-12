# OCRmyPDF AppleOCR

This is a plugin for [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF/) that enables OCR using the Apple Vision Framework on macOS.

## Installation

```bash
pip install ocrmypdf-appleocr
```

## Usage

```bash
ocrmypdf -l jpn --plugin ocrmypdf_appleocr input.pdf output.pdf
ocrmypdf -l jpn --plugin ocrmypdf_appleocr input.pdf output.pdf
```

Note that only [`hocr` renderer](https://ocrmypdf.readthedocs.io/en/latest/advanced.html#changing-the-pdf-renderer) is supported for this plugin.


## Options

- `--appleocr-disable-correction`: Disable language correction in Apple Vision OCR (default: False)
- `--appleocr-recognition-level`: Recognition level for Apple Vision OCR (default: accurate). Choices are `fast` and `accurate`.
- `-l` or `--language`: Specify the language(s) for OCR in ISO 639-2 three-letter codes. Use `und` for undetermined language. Combine

If you specify `und` or specify multiple languages, the plugin will attempt to detect the language using the `langdetect` library. Note that the accuracy of language detection may vary depending on the content of the document.