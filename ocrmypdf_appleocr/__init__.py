import sys
from pathlib import Path
import logging
from ocrmypdf import OcrEngine, hookimpl
from ocrmypdf._exec import tesseract

__version__ = "0.2.1"

log = logging.getLogger(__name__)

import objc
import Cocoa
import Vision
from PIL import Image
import langdetect

Textbox = tuple[str, float, float, float, float, float]

lang_code_map = {
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

lang_code_639_1_map = {
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


reverse_lang_code_map = {v: k for k, v in lang_code_map.items()}


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
        langs = options.appleocr_lang
        if langs:
            lang_codes = [
                lang_code_map.get(lang, lang)
                for lang in langs.split(",")
                if lang in lang_code_map
            ]
            recognize_request.setAutomaticallyDetectsLanguage_(False)
            recognize_request.setRecognitionLanguages_(lang_codes)
        else:
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
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return f"""<div class="ocr_carea" id="block_{page_number}_{line_number}" title="bbox {x} {y} {x + w} {y + h}">
<p class="ocr_par" id="par_{page_number}_{line_number}" lang="{lang}" title="bbox {x} {y} {x + w} {y + h}">
  <span class="ocr_line" id="line_{page_number}_{line_number}" title="bbox {x} {y} {x + w} {y + h}">
    <span class="ocrx_word" id="word_{page_number}_{line_number}" title="bbox {x} {y} {x + w} {y + h}; x_wconf {confidence}">{text}</span>
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


def build_hocr_document(image: Path, options) -> str:
    textboxes, width, height = ocr_macos_live_text(image, options)
    lang = options.appleocr_lang
    if not lang or "," in lang:
        text = "".join(tb[0] for tb in textboxes)
        lang = lang_code_639_1_map.get(langdetect.detect(text), "und")
    content = "".join(build_hocr_line(tb, 0, i, lang) for i, tb in enumerate(textboxes))
    res = hocr_template.format(content=content, width=width, height=height)
    return res


@hookimpl
def add_options(parser):
    appleocr_options = parser.add_argument_group(
        "Apple OCR", "Apple Vision OCR options"
    )
    appleocr_options.add_argument(
        "--appleocr-lang",
        type=str,
        help="Language for Apple Vision OCR (default: None, which means auto-detect)",
        default=None,
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


class AppleOCREngine(OcrEngine):
    """Implements OCR with Apple Vision Framework."""

    @staticmethod
    def version():
        return __version__

    @staticmethod
    def creator_tag(options):
        tag = "-PDF" if options.pdf_renderer == "sandwich" else ""
        return f"Apple Vision {tag} {AppleOCREngine.version()}"

    def __str__(self):
        return f"Apple Vision {AppleOCREngine.version()}"

    @staticmethod
    def languages(options):
        res = []
        for (
            lang
        ) in Vision.VNRecognizeTextRequest().supportedRecognitionLanguagesAndReturnError_(
            None
        ):
            l3 = reverse_lang_code_map.get(lang, None)
            if l3:
                res.append(l3)
        return res

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
        res = build_hocr_document(Path(input_file), options)
        with open(output_hocr, "w", encoding="utf-8") as f:
            f.write(res)

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        raise NotImplementedError(
            "Apple Vision OCR embedder does not support PDF output yet -- use --pdf-renderer=hocr for now."
        )


@hookimpl
def get_ocr_engine():
    return AppleOCREngine()
