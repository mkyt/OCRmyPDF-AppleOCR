import math
import multiprocessing as mp
import platform
import queue
import time
from pathlib import Path
from typing import Literal

import Cocoa
import objc
import Vision
from PyObjCTools import AppHelper

Vision  # to silence unused import warning

from ocrmypdf_appleocr.common import BoundingBox, Point, Textbox, locale_to_lang_code, log

livetext_supported = int(platform.mac_ver()[0].split(".")[0]) >= 13  # macOS Ventura or later
OCR_TIMEOUT = 30  # seconds to wait for the recognition subprocess
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


def _quad2pts(q, width, height) -> list[tuple[float, float]]:
    return [
        (q.topLeft().x * width, q.topLeft().y * height),
        (q.topRight().x * width, q.topRight().y * height),
        (q.bottomRight().x * width, q.bottomRight().y * height),
        (q.bottomLeft().x * width, q.bottomLeft().y * height),
    ]


def _quad2bb(q, ul_index, width, height) -> BoundingBox:
    pts = _quad2pts(q, width, height)
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    # sort points in CW order in x-right, y-down coordinate system
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    ul = Point(*pts[ul_index])
    ur = Point(*pts[(ul_index + 1) % 4])
    lr = Point(*pts[(ul_index + 2) % 4])
    ll = Point(*pts[(ul_index + 3) % 4])
    return BoundingBox(ul, ur, ll, lr)


def _nearest_pt_index(pts: list[tuple[float, float]], target: Point) -> int:
    return min(
        range(len(pts)),
        key=lambda i: (pts[i][0] - target.x) ** 2 + (pts[i][1] - target.y) ** 2,
    )


def _corner_map(q, bb: BoundingBox, width, height) -> tuple[int, int]:
    """Where the corners of `bb` sit in the point order VisionKit reports for `q`.

    Returns `(index of the upper-left corner, +1 or -1 for the winding)`, so that
    walking the quad points from that index in that direction yields ul, ur, lr, ll.

    Which corner of a quad is the upper-left one cannot be recovered from the quad
    alone: `_quad2ulIdx` picks the corner pointing closest to the upper left, which
    for a rotated quad depends on its aspect ratio, so the index it finds in the
    angle-sorted points of a line does not carry over to the narrow quads of its
    words. VisionKit does label the corners of a line and of its words by the same
    convention though, so the mapping resolved once for the line can be replayed on
    every word of that line.
    """
    pts = _quad2pts(q, width, height)
    i_ul = _nearest_pt_index(pts, bb.ul)
    step = 1 if _nearest_pt_index(pts, bb.ur) == (i_ul + 1) % 4 else -1
    return i_ul, step


def _quad2bb_mapped(q, corner_map: tuple[int, int], width, height) -> BoundingBox:
    """Convert a quad to a BoundingBox with the corner mapping of its line."""
    i_ul, step = corner_map
    pts = _quad2pts(q, width, height)

    def corner(n: int) -> Point:
        return Point(*pts[(i_ul + n * step) % 4])

    return BoundingBox(ul=corner(0), ur=corner(1), ll=corner(3), lr=corner(2))


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

                bb = _quad2bb(lq, ul_idx, width, height)

                if level == "word" and not is_vert:
                    corner_map = _corner_map(lq, bb, width, height)
                    children = []
                    for w in l.children():
                        wbb = _quad2bb_mapped(w.quad(), corner_map, width, height)
                        children.append(Textbox(w.string(), wbb, 100, is_vert, None))
                else:
                    children = None

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
    mp.set_start_method("spawn", force=True)
    q = mp.Queue()
    p = mp.Process(
        target=_ocr_VKCImageAnalyzerRequest_child_main,
        args=(q, image_file, width, height, locales, level),
    )
    p.start()
    # Read the result before waiting for the child to exit. A result larger than the
    # pipe buffer only leaves the child once it is drained from this end, so joining
    # first would deadlock on any page with enough text in it. Poll rather than block
    # for the whole timeout, so a child that dies without delivering anything is
    # noticed right away. `alive` is sampled before the read, so a child that exits
    # between the two still gets its result picked up.
    result = None
    deadline = time.monotonic() + OCR_TIMEOUT
    while result is None and time.monotonic() < deadline:
        alive = p.is_alive()
        try:
            result = q.get(timeout=0.1)
        except queue.Empty:
            if not alive:
                break
    # Still running means it never delivered a result; anything else failed outright.
    timed_out = p.is_alive()
    p.join(5)
    if p.is_alive():
        p.terminate()
        p.join()
    if result is None:
        raise RuntimeError(
            "Timeout in VKCImageAnalyzerRequest"
            if timed_out
            else "Error in performing VKCImageAnalyzerRequest"
        )

    return result
