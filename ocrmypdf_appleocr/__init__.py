import logging
import platform
from pathlib import Path

import pluggy
from ocrmypdf import OcrEngine, hookimpl
from ocrmypdf._exec import tesseract
from ocrmypdf.exceptions import ExitCodeException
from PIL import Image

from ocrmypdf_appleocr.common import Textbox, lang_code_to_locale, log
from ocrmypdf_appleocr.hocr import build_hocr_document
from ocrmypdf_appleocr.livetext import (
    livetext_supported,
    ocr_VKCImageAnalyzerRequest,
    supported_languages_livetext,
)
from ocrmypdf_appleocr.pdf import generate_pdf
from ocrmypdf_appleocr.vision import (
    ocr_VNRecognizeTextRequest,
    supported_languages_accurate,
    supported_languages_fast,
)

__version__ = "0.3.1"


def perform_ocr(image: Path, options) -> tuple[list[Textbox], int, int, tuple[int, int]]:
    im = Image.open(image)
    width, height = im.size
    dpi = im.info["dpi"]

    if options.appleocr_recognition_mode == "livetext":
        locales = [lang_code_to_locale.get(lang, lang) for lang in options.languages]
        textboxes = ocr_VKCImageAnalyzerRequest(image, width, height, locales)
    else:
        textboxes = ocr_VNRecognizeTextRequest(image, width, height, options)

    return textboxes, width, height, dpi


@hookimpl
def initialize(plugin_manager: pluggy.PluginManager):
    # Disable built-in Tesseract OCR engine to avoid conflict
    plugin_manager.set_blocked("ocrmypdf.builtin_plugins.tesseract_ocr")


@hookimpl
def add_options(parser):
    appleocr_options = parser.add_argument_group("Apple OCR", "Apple Vision OCR options")
    appleocr_options.add_argument(
        "--appleocr-disable-correction",
        action="store_true",
        help="Disable language correction in Apple Vision OCR (default: False)",
        default=False,
    )
    appleocr_options.add_argument(
        "--appleocr-recognition-mode",
        choices=["fast", "accurate", "livetext"],
        default="livetext" if livetext_supported else "accurate",
        help="Recognition mode for Apple Vision OCR (default: accurate for macOS 12 and earlier, livetext for macOS 13 and later)",
    )


@hookimpl
def check_options(options):
    if options.languages:
        if len(options.languages) == 1 and options.languages[0] == "und":
            if options.appleocr_recognition_mode == "livetext":
                raise ExitCodeException(
                    15, "Language detection is not supported by LiveText mode in Apple OCR"
                )
            options.languages = []
        supported_languages = AppleOCREngine.languages(options)
        for lang in options.languages:
            if "+" in lang:
                raise ExitCodeException(
                    15, "Language combination with '+' is not supported by Apple OCR."
                )
            if lang not in supported_languages:
                raise ExitCodeException(
                    15,
                    f"Language '{lang}' is not supported by Apple OCR (supported in {options.appleocr_recognition_mode} mode: {', '.join(supported_languages)}). Use 'und' for undetermined language.",
                )

    # Need to populate this value, as OCRmyPDF core uses it to determine if OCR should be performed.
    # cf. https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_pipelines/ocr.py#L122
    options.tesseract_timeout = 1

    if options.pdf_renderer == "auto":
        options.pdf_renderer = "sandwich"


class AppleOCREngine(OcrEngine):
    """Implements OCR with Apple Vision Framework."""

    @staticmethod
    def version():
        return __version__

    @staticmethod
    def creator_tag(options):
        os_version = platform.mac_ver()[0]
        return f"AppleOCR Plugin {AppleOCREngine.version()} (on macOS {os_version})"

    def __str__(self):
        return f"AppleOCR Plugin {AppleOCREngine.version()}"

    @staticmethod
    def languages(options):
        if options.appleocr_recognition_mode == "livetext":
            return supported_languages_livetext
        elif options.appleocr_recognition_mode == "accurate":
            return supported_languages_accurate
        else:
            return supported_languages_fast

    @staticmethod
    def get_orientation(input_file, options):
        return tesseract.get_orientation(
            input_file,
            engine_mode=options.tesseract_oem,
            timeout=options.tesseract_non_ocr_timeout,
        )

    @staticmethod
    def get_deskew(input_file, options) -> float:
        return 0.0

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        logging.debug("Starting OCR with Apple Vision Framework (hOCR renderer)...")

        ocr_result, width, height, _ = perform_ocr(Path(input_file), options)

        plaintext = "\n".join(tb.text for tb in ocr_result)

        hocr = build_hocr_document(ocr_result, width, height)
        with open(output_hocr, "w", encoding="utf-8") as f:
            f.write(hocr)
        with open(output_text, "w", encoding="utf-8") as f:
            f.write(plaintext)

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        logging.debug("Starting OCR with Apple Vision Framework (sandwich renderer)...")

        (
            res,
            w,
            h,
            dpi,
        ) = perform_ocr(Path(input_file), options)
        plaintext = "\n".join(tb.text for tb in res)

        generate_pdf(dpi, w, h, 1.0, res, Path(output_pdf), True)

        with open(output_text, "w", encoding="utf-8") as f:
            f.write(plaintext)


@hookimpl
def get_ocr_engine():
    return AppleOCREngine()
