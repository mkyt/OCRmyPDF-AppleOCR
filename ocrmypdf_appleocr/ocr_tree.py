from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ocrmypdf_appleocr.common import Textbox

if TYPE_CHECKING:
    from ocrmypdf.models.ocr_element import OcrElement


def _line_textangle(textbox: Textbox) -> float:
    """Text rotation in degrees, counter-clockwise, per hOCR/OcrElement convention.

    Mirrors the rotation used in ocrmypdf_appleocr.pdf.generate_text_content_stream to
    build the PDF text matrix: horizontal text advances along the box's own rotation,
    while vertical (top-to-bottom) text advances an additional 90 degrees clockwise
    relative to that.
    """
    angle = -math.degrees(textbox.bb.angle())
    if textbox.is_vertical:
        angle -= 90.0
    return angle


def _aabb(bb, BoundingBox):
    """Axis-aligned bounding box of a (possibly rotated) Textbox quad.

    As per [hOCR spec](https://kba.github.io/hocr-spec/1.2/#bbox),
    bbox should be specified by upper-left corner (x0, y0) and lower-right corner (x1, y1),
    but upstream (ocrmypdf core) assumes left < right and top < bottom, which do not hold for heavily rotated texts.
    For now, simply take the maximum/minimum of x and y coordinates as `bbox` to avoid errors.
    """
    xs = (bb.ul.x, bb.ur.x, bb.ll.x, bb.lr.x)
    ys = (bb.ul.y, bb.ur.y, bb.ll.y, bb.lr.y)
    bbox = BoundingBox(left=min(xs), top=min(ys), right=max(xs), bottom=max(ys))
    if bbox.width <= 0 or bbox.height <= 0:
        return None
    return bbox


def _word_elements(textbox: Textbox, BoundingBox, OcrClass, OcrElement) -> list[OcrElement]:
    """Word elements of a line, for languages that write words separated by spaces.

    The renderer places every word of a line on that line's own baseline and only
    uses the word box to decide where the word starts and how wide it is, so the
    per-word boxes cannot make the baseline wobble.
    """
    words = []
    for child in textbox.children or []:
        text = child.text.strip()
        bbox = _aabb(child.bb, BoundingBox)
        if not text or bbox is None:
            continue
        words.append(
            OcrElement(
                ocr_class=OcrClass.WORD,
                bbox=bbox,
                text=text,
                confidence=child.confidence / 100.0,
            )
        )
    return words


def build_ocr_tree(
    ocr_result: list[Textbox],
    width: int,
    height: int,
    dpi: tuple[float, float],
    page_number: int,
) -> OcrElement:
    """Convert Apple Vision OCR results into an ocrmypdf OcrElement tree.

    Each Textbox is Apple Vision's own unit of recognition (comparable to a whole
    line). It is split into its word children when the OCR engine reported them,
    and represented as a single-word ocr_line otherwise.
    """
    from ocrmypdf.models.ocr_element import BoundingBox, OcrClass, OcrElement

    lines = []
    for textbox in ocr_result:
        if not textbox.text:
            continue
        bbox = _aabb(textbox.bb, BoundingBox)
        if bbox is None:
            continue

        words = _word_elements(textbox, BoundingBox, OcrClass, OcrElement)
        if not words:
            words = [
                OcrElement(
                    ocr_class=OcrClass.WORD,
                    bbox=bbox,
                    text=textbox.text,
                    confidence=textbox.confidence / 100.0,
                )
            ]
        lines.append(
            OcrElement(
                ocr_class=OcrClass.LINE,
                bbox=bbox,
                textangle=_line_textangle(textbox),
                children=words,
            )
        )

    return OcrElement(
        ocr_class=OcrClass.PAGE,
        bbox=BoundingBox(left=0, top=0, right=width, bottom=height),
        dpi=float(dpi[0]),
        page_number=page_number,
        children=lines,
    )
