import math
import multiprocessing as mp
import platform
from pathlib import Path
from typing import Literal

import Cocoa
import objc
import Vision
from PyObjCTools import AppHelper

Vision  # to silence unused import warning

from ocrmypdf_appleocr.common import BoundingBox, Point, Textbox, locale_to_lang_code, log

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


def _quad2ulIdx(quad, width, height):
    pts = []
    pts.append((quad.topLeft().x * width, quad.topLeft().y * height))
    pts.append((quad.topRight().x * width, quad.topRight().y * height))
    pts.append((quad.bottomRight().x * width, quad.bottomRight().y * height))
    pts.append((quad.bottomLeft().x * width, quad.bottomLeft().y * height))
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0

    # sort points in CW order in x-right, y-down coordinate system
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

    ideal_ul_angle = -3 * math.pi / 4
    min_diff = float("inf")
    ul_index = -1
    for i, p in enumerate(pts):
        angle = math.atan2(p[1] - cy, p[0] - cx)
        diff = abs(angle - ideal_ul_angle)
        if diff > math.pi:
            diff = abs(diff - 2 * math.pi)
        if diff < min_diff:
            min_diff = diff
            ul_index = i
    return ul_index


def _quad2bb(q, ul_index, width, height) -> BoundingBox:
    pts = []
    pts.append((q.topLeft().x * width, q.topLeft().y * height))
    pts.append((q.topRight().x * width, q.topRight().y * height))
    pts.append((q.bottomRight().x * width, q.bottomRight().y * height))
    pts.append((q.bottomLeft().x * width, q.bottomLeft().y * height))
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    # sort points in CW order in x-right, y-down coordinate system
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    ul = Point(int(pts[ul_index][0]), int(pts[ul_index][1]))
    ur = Point(int(pts[(ul_index + 1) % 4][0]), int(pts[(ul_index + 1) % 4][1]))
    lr = Point(int(pts[(ul_index + 2) % 4][0]), int(pts[(ul_index + 2) % 4][1]))
    ll = Point(int(pts[(ul_index + 3) % 4][0]), int(pts[(ul_index + 3) % 4][1]))
    return BoundingBox(ul, ur, ll, lr)


def _ocr_VKCImageAnalyzerRequest_child_main(
    q: mp.Queue,
    image_file: Path,
    width: int,
    height: int,
    locales: list[str],
    level: Literal["line", "word"],
):
    result = None

    def _process_handler(analysis, error):
        nonlocal result
        lines: list[Textbox] = []
        response_lines = analysis.allLines()
        if response_lines:
            for l in response_lines:
                lq = l.quad()
                ul_idx = _quad2ulIdx(lq, width, height)
                # https://github.com/WebKit/WebKit/blob/main/Source/WebKit/Platform/cocoa/ImageAnalysisUtilities.mm
                is_vert = l.layoutDirection() == 5

                if level == "word" and not is_vert:
                    children = []
                    for w in l.children():
                        wq = w.quad()
                        bb = _quad2bb(wq, ul_idx, width, height)
                        children.append(Textbox(w.string(), bb, 100, is_vert, None))
                else:
                    children = None

                bb = _quad2bb(lq, ul_idx, width, height)
                lines.append(
                    Textbox(
                        l.string(),
                        bb,
                        100,  # VKCImageAnalyzer does not provide confidence score,
                        is_vert,
                        children,
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
    image_file: Path, width: int, height: int, locales: list[str], level: Literal["line", "word"]
) -> list[Textbox]:
    result = None

    mp.set_start_method("spawn", force=True)
    q = mp.Queue()
    p = mp.Process(
        target=_ocr_VKCImageAnalyzerRequest_child_main,
        args=(q, image_file, width, height, locales, level),
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
