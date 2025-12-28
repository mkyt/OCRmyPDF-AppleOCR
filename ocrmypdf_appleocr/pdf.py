# This code includes portions adapted from:
# https://github.com/ocrmypdf/OCRmyPDF-EasyOCR (MIT License)
# Copyright (c) 2023 James R. Barlow
# Modified by Masahiro Kiyota, 2025 to support vertical text in CJK languages

from __future__ import annotations

import importlib.resources
import math
from collections.abc import Iterable
from pathlib import Path

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

    def m(self, x: float, y: float):
        """Move to point (x, y)."""
        inst = [ContentStreamInstruction([x, y], Operator("m"))]
        return ContentStreamBuilder(self._instructions + inst)

    def l(self, x: float, y: float):
        """Draw line to point (x, y)."""
        inst = [ContentStreamInstruction([x, y], Operator("l"))]
        return ContentStreamBuilder(self._instructions + inst)

    def h(self):
        """Close path."""
        inst = [ContentStreamInstruction([], Operator("h"))]
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
        text = result.text
        # bbox is in up-left origin, pixel coordinates
        bbox = result.bb
        box_width = bbox.true_width() * scale[0]
        box_height = bbox.true_height() * scale[1]
        angle = -bbox.angle()  # PDF coordinate is y-up, so negate the angle
        ulx = bbox.ul.x * scale[0]
        uly = (height - bbox.ul.y) * scale[1]
        llx = bbox.ll.x * scale[0]
        lly = (height - bbox.ll.y) * scale[1]
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        if len(text) == 0 or box_width <= 0 or box_height <= 0:
            continue

        vertical = result.is_vertical

        log.debug(
            f"Textline '{text}' bbox (in px): {bbox} vertical: {vertical}, angle: {angle}, box_width: {box_width}, box_height: {box_height}"
        )

        if vertical:
            font_size = box_width
            stretch = 100.0 * box_height / len(text) / font_size * CHAR_ASPECT
            tm_args = (
                font_size * sin_a,
                -font_size * cos_a,
                font_size * cos_a,
                -font_size * sin_a,
                ulx,
                uly,
            )
        else:
            font_size = box_height
            stretch = 100.0 * box_width / len(text) / font_size * CHAR_ASPECT
            tm_args = (
                font_size * cos_a,
                font_size * sin_a,
                -font_size * sin_a,
                font_size * cos_a,
                llx,
                lly,
            )

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
            urx = bbox.ur.x * scale[0]
            ury = (height - bbox.ur.y) * scale[1]
            lrx = bbox.lr.x * scale[0]
            lry = (height - bbox.lr.y) * scale[1]
            cs = cs.add(
                ContentStreamBuilder()
                .q()
                .RG(1.0, 0.0, 0.0)
                .w(0.75)
                .m(ulx, uly)
                .l(urx, ury)
                .l(lrx, lry)
                .l(llx, lly)
                .h()
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
