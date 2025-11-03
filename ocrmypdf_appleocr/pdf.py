# This code includes portions adapted from:
# https://github.com/ocrmypdf/OCRmyPDF-EasyOCR (MIT License)
# Copyright (c) 2023 James R. Barlow
# Modified by Masahiro Kiyota, 2025 to support vertical text in CJK languages

from __future__ import annotations

import importlib.resources
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from pikepdf import (
    ContentStreamInstruction,
    Dictionary,
    Name,
    Operator,
    Pdf,
    unparse_content_stream,
)

from ocrmypdf_appleocr.common import Textbox, log

TEXT_POSITION_DEBUG = False
GLYPHLESS_FONT = importlib.resources.read_binary("ocrmypdf_appleocr", "pdf.ttf")
CHAR_ASPECT = 2
FONT_NAME = Name("/f-0-0")


class BBox(NamedTuple):
    x1: float
    y1: float
    x2: float
    y2: float


def pt_from_pixel(bbox: Textbox, scale: tuple[float, float], height: int):
    """Convert pixel coordinates to PDF points.
      llx, lly, urx, ury
    where origin is at bottom-left corner
    """
    x1 = bbox.x * scale[0]
    y1 = (height - bbox.y - bbox.h) * scale[1]
    x2 = (bbox.x + bbox.w) * scale[0]
    y2 = (height - bbox.y) * scale[1]
    return BBox(x1, y1, x2, y2)


def bbox_string(bbox: BBox):
    return str(bbox)


def contains_cjk(text: str) -> bool:
    for ch in text:
        codepoint = ord(ch)
        if (
            0x4E00 <= codepoint <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= codepoint <= 0x4DBF  # CJK Unified Ideographs Extension A
            or 0x20000 <= codepoint <= 0x2CEAF  # Extensions B-F
            or 0xF900 <= codepoint <= 0xFAFF  # CJK Compatibility Ideographs
            or 0x2F800 <= codepoint <= 0x2FA1F  # Compatibility Supplement
            or 0x3040 <= codepoint <= 0x30FF  # Hiragana/Katakana
            or 0x31F0 <= codepoint <= 0x31FF  # Katakana Phonetic Extensions
            or 0xAC00 <= codepoint <= 0xD7A3  # Hangul Syllables
        ):
            return True
    return False


def should_render_vertical(textbox: Textbox) -> bool:
    text = textbox.text.strip()
    if len(text) <= 1:
        return False
    if textbox.w <= 0 or textbox.h <= 0:
        return False
    if not contains_cjk(text):
        return False

    aspect_ratio = textbox.h / textbox.w
    if aspect_ratio < 1.2:
        return False

    return True


def register_glyphlessfont(pdf: Pdf):
    """Register the glyphless font.

    Create several data structures in the Pdf to describe the font. While it create
    the data, a reference should be set in at least one page's /Resources dictionary
    to retain the font in the output PDF and ensure it is usable on that page.
    """
    PLACEHOLDER = Name.Placeholder

    basefont = pdf.make_indirect(
        Dictionary(
            BaseFont=Name.GlyphLessFont,
            DescendantFonts=[PLACEHOLDER],
            Encoding=Name("/Identity-H"),
            Subtype=Name.Type0,
            ToUnicode=PLACEHOLDER,
            Type=Name.Font,
        )
    )
    cid_font_type2 = pdf.make_indirect(
        Dictionary(
            BaseFont=Name.GlyphLessFont,
            CIDToGIDMap=PLACEHOLDER,
            CIDSystemInfo=Dictionary(
                Ordering="Identity",
                Registry="Adobe",
                Supplement=0,
            ),
            FontDescriptor=PLACEHOLDER,
            Subtype=Name.CIDFontType2,
            Type=Name.Font,
            DW=1000 // CHAR_ASPECT,
        )
    )
    basefont.DescendantFonts = [cid_font_type2]
    cid_font_type2.CIDToGIDMap = pdf.make_stream(b"\x00\x01" * 65536)
    basefont.ToUnicode = pdf.make_stream(
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin\n"
        b"begincmap\n"
        b"/CIDSystemInfo\n"
        b"<<\n"
        b"  /Registry (Adobe)\n"
        b"  /Ordering (UCS)\n"
        b"  /Supplement 0\n"
        b">> def\n"
        b"/CMapName /Adobe-Identify-UCS def\n"
        b"/CMapType 2 def\n"
        b"1 begincodespacerange\n"
        b"<0000> <FFFF>\n"
        b"endcodespacerange\n"
        b"1 beginbfrange\n"
        b"<0000> <FFFF> <0000>\n"
        b"endbfrange\n"
        b"endcmap\n"
        b"CMapName currentdict /CMap defineresource pop\n"
        b"end\n"
        b"end\n"
    )
    font_descriptor = pdf.make_indirect(
        Dictionary(
            Ascent=1000,
            CapHeight=1000,
            Descent=-1,
            Flags=5,  # Fixed pitch and symbolic
            FontBBox=[0, 0, 1000 // CHAR_ASPECT, 1000],
            FontFile2=PLACEHOLDER,
            FontName=Name.GlyphLessFont,
            ItalicAngle=0,
            StemV=80,
            Type=Name.FontDescriptor,
        )
    )
    font_descriptor.FontFile2 = pdf.make_stream(GLYPHLESS_FONT)
    cid_font_type2.FontDescriptor = font_descriptor
    return basefont


class ContentStreamBuilder:
    def __init__(self, instructions=None):
        self._instructions = instructions or []

    def q(self):
        """Save the graphics state."""
        inst = [ContentStreamInstruction([], Operator("q"))]
        return ContentStreamBuilder(self._instructions + inst)

    def Q(self):
        """Restore the graphics state."""
        inst = [ContentStreamInstruction([], Operator("Q"))]
        return ContentStreamBuilder(self._instructions + inst)

    def cm(self, a: float, b: float, c: float, d: float, e: float, f: float):
        """Concatenate matrix."""
        inst = [ContentStreamInstruction([a, b, c, d, e, f], Operator("cm"))]
        return ContentStreamBuilder(self._instructions + inst)

    def BT(self):
        """Begin text object."""
        inst = [ContentStreamInstruction([], Operator("BT"))]
        return ContentStreamBuilder(self._instructions + inst)

    def ET(self):
        """End text object."""
        inst = [ContentStreamInstruction([], Operator("ET"))]
        return ContentStreamBuilder(self._instructions + inst)

    def BDC(self, mctype: Name, mcid: int):
        """Begin marked content sequence."""
        inst = [ContentStreamInstruction([mctype, Dictionary(MCID=mcid)], Operator("BDC"))]
        return ContentStreamBuilder(self._instructions + inst)

    def EMC(self):
        """End marked content sequence."""
        inst = [ContentStreamInstruction([], Operator("EMC"))]
        return ContentStreamBuilder(self._instructions + inst)

    def Tf(self, font: Name, size: int):
        """Set text font and size."""
        inst = [ContentStreamInstruction([font, size], Operator("Tf"))]
        return ContentStreamBuilder(self._instructions + inst)

    def Tm(self, a: float, b: float, c: float, d: float, e: float, f: float):
        """Set text matrix."""
        inst = [ContentStreamInstruction([a, b, c, d, e, f], Operator("Tm"))]
        return ContentStreamBuilder(self._instructions + inst)

    def Tr(self, mode: int):
        """Set text rendering mode."""
        inst = [ContentStreamInstruction([mode], Operator("Tr"))]
        return ContentStreamBuilder(self._instructions + inst)

    def Tz(self, scale: float):
        """Set text horizontal scaling."""
        inst = [ContentStreamInstruction([scale], Operator("Tz"))]
        return ContentStreamBuilder(self._instructions + inst)

    def TJ(self, text):
        """Show text."""
        inst = [ContentStreamInstruction([[text.encode("utf-16be")]], Operator("TJ"))]
        return ContentStreamBuilder(self._instructions + inst)

    def s(self):
        """Stroke and close path."""
        inst = [ContentStreamInstruction([], Operator("s"))]
        return ContentStreamBuilder(self._instructions + inst)

    def re(self, x: float, y: float, w: float, h: float):
        """Append rectangle to path."""
        inst = [ContentStreamInstruction([x, y, w, h], Operator("re"))]
        return ContentStreamBuilder(self._instructions + inst)

    def RG(self, r: float, g: float, b: float):
        """Set RGB stroke color."""
        inst = [ContentStreamInstruction([r, g, b], Operator("RG"))]
        return ContentStreamBuilder(self._instructions + inst)

    def w(self, width: float):
        """Set line width."""
        inst = [ContentStreamInstruction([width], Operator("w"))]
        return ContentStreamBuilder(self._instructions + inst)

    def S(self):
        """Stroke path."""
        inst = [ContentStreamInstruction([], Operator("S"))]
        return ContentStreamBuilder(self._instructions + inst)

    def build(self):
        return self._instructions

    def add(self, other: ContentStreamBuilder):
        return ContentStreamBuilder(self._instructions + other._instructions)


def generate_text_content_stream(
    results: Iterable[Textbox],
    scale: tuple[float, float],
    height: int,
    boxes=False,
):
    """Generate a content stream for the described by results.

    Args:
        results (Iterable[Textbox]): Results of OCR.
        scale (tuple[float, float]): Scale of the image.
        height (int): Height of the image.

    Yields:
        ContentStreamInstruction: Content stream instructions.
    """

    cs = ContentStreamBuilder()
    cs = cs.add(cs.q())
    for n, result in enumerate(results):
        bbox = pt_from_pixel(result, scale, height)

        text = result.text
        box_width = bbox.x2 - bbox.x1
        box_height = bbox.y2 - bbox.y1

        if len(text) == 0 or box_width <= 0 or box_height <= 0:
            continue

        vertical = should_render_vertical(result)

        log.debug(f"Textline '{text}' PDF bbox: {bbox_string(bbox)} vertical: {vertical}")

        if vertical:
            font_size = box_width
            stretch = 100.0 * box_height / len(text) / font_size * CHAR_ASPECT
            tm_args = (0, -font_size, font_size, 0, bbox.x1, bbox.y2)
        else:
            font_size = box_height
            stretch = 100.0 * box_width / len(text) / font_size * CHAR_ASPECT
            tm_args = (font_size, 0, 0, font_size, bbox.x1, bbox.y1)

        cs = cs.add(
            ContentStreamBuilder()
            .BT()
            .BDC(Name.Span, n)
            .Tr(3)  # Invisible ink
            .Tm(*tm_args)
            .Tf(FONT_NAME, 1)
            .Tz(stretch)
            .TJ(text)
            .EMC()
            .ET()
        )
        if boxes:
            cs = cs.add(
                ContentStreamBuilder()
                .q()
                .RG(1.0, 0.0, 0.0)
                .w(0.75)
                .re(bbox.x1, bbox.y1, box_width, box_height)
                .S()
                .Q()
            )

    cs = cs.Q()
    return cs.build()


def generate_pdf(
    dpi: tuple[float, float],
    width: int,
    height: int,
    image_scale: float,
    results: Iterable[Textbox],
    output_pdf: Path,
    boxes: bool,
):
    """Convert OCR results to a PDF with text annotations (no images).

    Args:
        dpi: DPI of the OCR image.
        width: Width of the OCR image in pixels.
        height: Height of the OCR image in pixels.
        image_scale: Scale factor applied to the OCR image. 1.0 means the
            image is at the scale implied by its DPI. 2.0 means the image
            is twice as large as implied by its DPI.
        results: List of Textbox objects.
        output_pdf: Path to the output PDF file that this will function will
            create.

    Returns:
        output_pdf
    """

    scale = 72.0 / dpi[0] / image_scale, 72.0 / dpi[1] / image_scale

    with Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(width * scale[0], height * scale[1]))
        pdf.pages[0].Resources = Dictionary(
            Font=Dictionary(
                {
                    str(FONT_NAME): register_glyphlessfont(pdf),
                }
            )
        )

        cs = generate_text_content_stream(results, scale, height, boxes=boxes)
        pdf.pages[0].Contents = pdf.make_stream(unparse_content_stream(cs))

        pdf.save(output_pdf)
    return output_pdf
