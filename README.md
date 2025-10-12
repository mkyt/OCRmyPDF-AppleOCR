# OCRmyPDF AppleOCR

This is a plugin for [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF/) that enables OCR using the text detection feature (`RecognizeTextRequest`) of [Apple Vision Framework](https://developer.apple.com/documentation/vision) on macOS.

Apple's proprietary implementation offers good accuracy and speed compared to other on-device OCR engines like Tesseract.

## Installation

The package is available on [PyPI](https://pypi.org/project/ocrmypdf-appleocr/).

```bash
pip install ocrmypdf-appleocr
```

## Usage

To use the plugin, specify the `--plugin` option when running `ocrmypdf`. You can also specify the language(s) for OCR using the `-l` or `--language` option. If you want to enable automatic language detection, use `und` (undetermined) as the language code.

```bash
ocrmypdf -l jpn --plugin ocrmypdf_appleocr input.pdf output.pdf
```

Note that [`sandwich` renderer](https://ocrmypdf.readthedocs.io/en/latest/advanced.html#changing-the-pdf-renderer) is not supported on this plugin.


## Options

- `--appleocr-disable-correction`: Disable language correction in Apple Vision OCR (default: False)
- `--appleocr-recognition-level`: Recognition level for Apple Vision OCR (default: accurate). Choices are `fast` and `accurate`.
- `-l` or `--language`: Specify the language(s) for OCR in ISO 639-2 three-letter codes. Use `und` for undetermined language. Specifying multiple languages using `+` (e.g. `eng+fra`) for multilingual documents is not supported.

If you specify `und` or specify multiple languages, the plugin will attempt to detect the language using the `langdetect` library. Note that the accuracy of language detection may vary depending on the content of the document.