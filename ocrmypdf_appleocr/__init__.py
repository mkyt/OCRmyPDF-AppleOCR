import sys
from pathlib import Path
import logging
from ocrmypdf import OcrEngine, hookimpl
from ocrmypdf._exec import tesseract
from ocrmypdf.exceptions import ExitCodeException
import pluggy

__version__ = "0.2.2"

log = logging.getLogger(__name__)

import objc
import Cocoa
import Vision
from PIL import Image
import langdetect

Textbox = tuple[str, float, float, float, float, float]

lang_code_to_locale = {
    "eng": "en-US",
    "fra": "fr-FR",
    "ita": "it-IT",
    "deu": "de-DE",
    "spa": "es-ES",
    "por": "pt-BR",
    "chi_sim": "zh-Hans",
    "chi_tra": "zh-Hant",
    "kor": "ko-KR",
    "jpn": "ja-JP",
    "rus": "ru-RU",
    "ukr": "uk-UA",
    "tha": "th-TH",
    "vie": "vi-VT",
    "ara": "ar-SA",
    "ars": "ars-SA",
    "tur": "tr-TR",
    "ind": "id-ID",
    "ces": "cs-CZ",
    "dan": "da-DK",
    "nld": "nl-NL",
    "nor": "no-NO",
    "nno": "nn-NO",
    "nob": "nb-NO",
    "msa": "ms-MY",
    "pol": "pl-PL",
    "ron": "ro-RO",
    "swe": "sv-SE",
}

locale_to_lang_code = {v: k for k, v in lang_code_to_locale.items()}

lang_code_two_letter_to_three_letter = {
    "en": "eng",
    "fr": "fra",
    "it": "ita",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "zh-cn": "chi_sim",
    "zh-tw": "chi_tra",
    "ko": "kor",
    "ja": "jpn",
    "ru": "rus",
    "uk": "ukr",
    "th": "tha",
    "vi": "vie",
    "ar": "ara",
    "tr": "tur",
    "id": "ind",
    "cs": "ces",
    "da": "dan",
    "nl": "nld",
    "no": "nor",
}

supported_languages = []
with objc.autorelease_pool():
     lst, _ = Vision.VNRecognizeTextRequest.alloc().init().supportedRecognitionLanguagesAndReturnError_(
            None
        )
     for locale in lst:
        if locale in locale_to_lang_code:
            supported_languages.append(locale_to_lang_code[locale])


def ocr_macos_live_text(
    image_file: Path | str, options
) -> tuple[list[Textbox], int, int]:
    def read_observation(
        o: Vision.VNRecognizedTextObservation, image_width: int, image_height: int
    ) -> Textbox:
        recognized_text: Vision.VNRecognizedText = o.topCandidates_(1)[0]
        bb = o.boundingBox()
        x, y, w, h = (
            bb.origin.x,
            1 - bb.origin.y - bb.size.height,
            bb.size.width,
            bb.size.height,
        )
        confidence = recognized_text.confidence()
        text = recognized_text.string()
        return (
            text,
            int(x * image_width),
            int(y * image_height),
            int(w * image_width),
            int(h * image_height),
            int(confidence * 100),
        )

    width, height = Image.open(image_file).size

    with objc.autorelease_pool():
        recognize_request = Vision.VNRecognizeTextRequest.alloc().init()
        if options.languages:
            locales = [
                lang_code_to_locale.get(lang, lang)
                for lang in options.languages
            ]
            recognize_request.setAutomaticallyDetectsLanguage_(False)
            recognize_request.setRecognitionLanguages_(locales)
        else:
            log.debug("No language specified, using automatic language detection")
            recognize_request.setAutomaticallyDetectsLanguage_(True)
        if options.appleocr_disable_correction:
            recognize_request.setUsesLanguageCorrection_(False)
        else:
            recognize_request.setUsesLanguageCorrection_(True)
        level = options.appleocr_recognition_level
        if level == "fast":
            recognize_request.setRecognitionLevel_(
                Vision.VNRequestTextRecognitionLevelFast
            )
        request_handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            Cocoa.NSURL.fileURLWithPath_(image_file.absolute().as_posix()), None
        )
        _, error = request_handler.performRequests_error_([recognize_request], None)
        if error:
            raise RuntimeError(f"Error in Live Text {error=}")
        res = [read_observation(o, width, height) for o in recognize_request.results()]
    return res, width, height


def build_hocr_line(
    textbox: Textbox, page_number: int, line_number: int, lang: str
) -> str:
    text, x, y, w, h, confidence = textbox
    bbox = f'bbox {x} {y} {x + w} {y + h}'
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return f"""<div class="ocr_carea" id="block_{page_number}_{line_number}" title="{bbox}">
<p class="ocr_par" id="par_{page_number}_{line_number}" lang="{lang}" title="{bbox}">
  <span class="ocr_line" id="line_{page_number}_{line_number}" title="{bbox}">
    <span class="ocrx_word" id="word_{page_number}_{line_number}" title="{bbox}; x_wconf {confidence}">{text}</span>
  </span>
</p>
</div>
"""


hocr_template = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
<title></title>
<meta http-equiv="Content-Type" content="text/html;charset=utf-8"/>
<meta name="ocr-system" content="" />
<meta name="ocr-capabilities" content="ocr_page ocr_carea ocr_par ocr_line ocrx_word"/>
</head>
<body>
<div class="ocr_page" id="page_0" title="bbox 0 0 {width} {height}">
{content}
</div>
</body>
</html>
"""


def build_hocr_document(image: Path, options) -> tuple[str, str]:
    textboxes, width, height = ocr_macos_live_text(image, options)
    plaintext = "\n".join(tb[0] for tb in textboxes)
    if options.languages and len(options.languages) == 1:
        lang = options.languages[0]
    else:
        try:
            lang_ISO639_2 = langdetect.detect(plaintext)
            lang = lang_code_two_letter_to_three_letter.get(lang_ISO639_2, "und")
        except Exception:
            lang = "und"
    content = "".join(build_hocr_line(tb, 0, i, lang) for i, tb in enumerate(textboxes))
    hocr = hocr_template.format(content=content, width=width, height=height)
    return hocr, plaintext


@hookimpl
def initialize(plugin_manager: pluggy.PluginManager):
    # Disable built-in Tesseract OCR engine to avoid conflict
    plugin_manager.set_blocked("ocrmypdf.builtin_plugins.tesseract_ocr")


@hookimpl
def add_options(parser):
    appleocr_options = parser.add_argument_group(
        "Apple OCR", "Apple Vision OCR options"
    )
    appleocr_options.add_argument(
        "--appleocr-disable-correction",
        action="store_true",
        help="Disable language correction in Apple Vision OCR (default: False)",
        default=False,
    )
    appleocr_options.add_argument(
        "--appleocr-recognition-level",
        choices=["fast", "accurate"],
        default="accurate",
        help="Recognition level for Apple Vision OCR (default: accurate)",
    )

@hookimpl
def check_options(options):
    if options.languages:
        if len(options.languages) == 1 and options.languages[0] == "und":
            options.languages = []
        for lang in options.languages:
            if '+' in lang:
                raise ExitCodeException(15, "Language combination with '+' is not supported by Apple OCR.")
            if lang not in supported_languages:
                raise ExitCodeException(15, f"Language '{lang}' is not supported by Apple OCR (engine supports: {', '.join(supported_languages)}). Use 'und' for undetermined language.")

    # Need to populate this value, as OCRmyPDF core uses it to determine if OCR should be performed.
    # cf. https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_pipelines/ocr.py#L122
    options.tesseract_timeout = 1

    if options.pdf_renderer == 'auto':
        options.pdf_renderer = 'hocr'
    elif options.pdf_renderer == 'sandwich':
        raise ExitCodeException(15, "--pdf-renderer=sandwich is not supported by Apple OCR. Use --pdf-renderer=hocr.")

class AppleOCREngine(OcrEngine):
    """Implements OCR with Apple Vision Framework."""

    @staticmethod
    def version():
        return __version__

    @staticmethod
    def creator_tag(options):
        return f"AppleOCR Plugin {AppleOCREngine.version()}"

    def __str__(self):
        return f"AppleOCR Plugin {AppleOCREngine.version()}"

    @staticmethod
    def languages(options):
        return supported_languages

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
        hocr, plaintext = build_hocr_document(Path(input_file), options)
        with open(output_hocr, "w", encoding="utf-8") as f:
            f.write(hocr)
        with open(output_text, "w", encoding="utf-8") as f:
            f.write(plaintext)

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        raise NotImplementedError(
            "Apple Vision OCR embedder does not support the sandwich renderer. Use --pdf-renderer=hocr instead."
        )


@hookimpl
def get_ocr_engine():
    return AppleOCREngine()
