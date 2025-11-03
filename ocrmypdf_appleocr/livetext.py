import multiprocessing as mp
import platform
from pathlib import Path

import Cocoa
import objc
import Vision
from PyObjCTools import AppHelper

Vision  # to silence unused import warning

from ocrmypdf_appleocr.common import Textbox, locale_to_lang_code, log

livetext_supported = int(platform.mac_ver()[0].split(".")[0]) >= 13  # macOS Ventura or later
supported_languages_livetext: list[str] = []
if livetext_supported:
    app_info = Cocoa.NSBundle.mainBundle().infoDictionary()
    app_info["LSBackgroundOnly"] = "1"
    objc.registerMetaDataForSelector(
        b"VKCImageAnalyzer",
        b"processRequest:progressHandler:completionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"d"},
                        },
                    }
                },
                4: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"@"},
                            2: {"type": b"@"},
                        },
                    }
                },
            }
        },
    )
    VKCImageAnalyzer = objc.lookUpClass("VKCImageAnalyzer")
    VKCImageAnalyzerRequest = objc.lookUpClass("VKCImageAnalyzerRequest")
    with objc.autorelease_pool():
        for locale in VKCImageAnalyzer.supportedRecognitionLanguages():
            if locale in locale_to_lang_code:
                supported_languages_livetext.append(locale_to_lang_code[locale])
            else:
                log.debug(f"Locale '{locale}' not mapped to any language code.")


def _ocr_VKCImageAnalyzerRequest_child_main(
    q: mp.Queue, image_file: Path, width: int, height: int, locales: list[str]
):
    result = None

    def _process_handler(analysis, error):
        nonlocal result
        lines = []
        response_lines = analysis.allLines()
        if response_lines:
            for l in response_lines:
                l_bbox = l.quad().boundingBox()
                lines.append(
                    (
                        l.string(),
                        int(l_bbox.origin.x * width),
                        int(l_bbox.origin.y * height),
                        int(l_bbox.size.width * width),
                        int(l_bbox.size.height * height),
                        100,  # VKCImageAnalyzer does not provide confidence score
                    )
                )
        AppHelper.stopEventLoop()
        result = lines

    with objc.autorelease_pool():
        analyzer = VKCImageAnalyzer.alloc().init()
        nsimg = Cocoa.NSImage.alloc().initWithContentsOfFile_(image_file.as_posix())
        req = VKCImageAnalyzerRequest.alloc().initWithImage_requestType_(
            nsimg,
            1,  # 1 == VKAnalysisTypeText
        )
        req.setLocales_(locales)
        analyzer.processRequest_progressHandler_completionHandler_(
            req, lambda progress: None, _process_handler
        )
        # Wait for completion
        AppHelper.runConsoleEventLoop()

    if result is None:
        result = []
        raise RuntimeError("Error in performing VKCImageAnalyzerRequest")

    q.put(result)


def ocr_VKCImageAnalyzerRequest(
    image_file: Path, width: int, height: int, locales: list[str]
) -> list[Textbox]:
    result = None

    mp.set_start_method("spawn", force=True)
    q = mp.Queue()
    p = mp.Process(
        target=_ocr_VKCImageAnalyzerRequest_child_main,
        args=(q, image_file, width, height, locales),
    )
    p.start()
    p.join(30)  # Timeout after 30 seconds
    if p.is_alive():
        p.terminate()
        p.join()
        raise RuntimeError("Timeout in VKCImageAnalyzerRequest")
    if not q.empty():
        result = q.get()
    if result is None:
        result = []
        raise RuntimeError("Error in performing VKCImageAnalyzerRequest")

    return result
