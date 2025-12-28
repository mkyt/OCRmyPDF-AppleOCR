from pathlib import Path

import Cocoa
import objc
import Vision

from ocrmypdf_appleocr.common import (
    BoundingBox,
    Point,
    Textbox,
    lang_code_to_locale,
    locale_to_lang_code,
    log,
)

supported_languages_accurate: list[str] = []
supported_languages_fast: list[str] = []
with objc.autorelease_pool():
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    lst, _ = req.supportedRecognitionLanguagesAndReturnError_(None)
    for locale in lst:
        if locale in locale_to_lang_code:
            supported_languages_accurate.append(locale_to_lang_code[locale])
        else:
            log.debug(f"Locale '{locale}' not mapped to any language code.")
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
    lst, _ = req.supportedRecognitionLanguagesAndReturnError_(None)
    for locale in lst:
        if locale in locale_to_lang_code:
            supported_languages_fast.append(locale_to_lang_code[locale])
        else:
            log.debug(f"Locale '{locale}' not mapped to any language code.")


def ocr_VNRecognizeTextRequest(image_file: Path, width: int, height: int, options) -> list[Textbox]:
    with objc.autorelease_pool():
        recognize_request = Vision.VNRecognizeTextRequest.alloc().init()
        if options.languages:
            locales = [lang_code_to_locale.get(lang, lang) for lang in options.languages]
            recognize_request.setAutomaticallyDetectsLanguage_(False)
            recognize_request.setRecognitionLanguages_(locales)
        else:
            log.debug("Using automatic language detection.")
            recognize_request.setAutomaticallyDetectsLanguage_(True)
        if options.appleocr_disable_correction:
            recognize_request.setUsesLanguageCorrection_(False)
        else:
            recognize_request.setUsesLanguageCorrection_(True)
        level = options.appleocr_recognition_mode
        if level == "fast":
            recognize_request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
        elif level == "accurate":
            recognize_request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        else:
            raise RuntimeError(
                f"VNRecognizeTextRequest does not support recognition level '{level}'"
            )
        request_handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            Cocoa.NSURL.fileURLWithPath_(image_file.absolute().as_posix()), None
        )
        _, error = request_handler.performRequests_error_([recognize_request], None)
        if error:
            raise RuntimeError(f"Error in performing VNRecognizeTextRequest: {error=}")
        res: list[Textbox] = []
        for o in recognize_request.results():
            recognized_text: Vision.VNRecognizedText = o.topCandidates_(1)[0]
            bb = o.boundingBox()  # bb in bottom-left origin, normalized coordinates
            b = BoundingBox(  # b in upper-left origin, pixel coordinates
                Point(
                    int(bb.origin.x * width), int((1 - bb.origin.y - bb.size.height) * height)
                ),  # ul
                Point(
                    int((bb.origin.x + bb.size.width) * width),
                    int((1 - bb.origin.y - bb.size.height) * height),
                ),  # ur
                Point(int(bb.origin.x * width), int((1 - bb.origin.y) * height)),  # ll
                Point(
                    int((bb.origin.x + bb.size.width) * width), int((1 - bb.origin.y) * height)
                ),  # lr
            )
            confidence = recognized_text.confidence()
            text = recognized_text.string()
            res.append(
                Textbox(
                    text,
                    b,
                    int(confidence * 100),
                    False,  # VNRecognizeTextRequest does not provide orientation info
                )
            )
    return res
