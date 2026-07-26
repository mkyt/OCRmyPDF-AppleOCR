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
# Minimum width of the space rendered between two words, as a fraction of the font size
MIN_SPACE_RATIO = 0.1
# Fraction of the line box height (width, for vertical text) actually covered by the
# rendered glyphs. The reported line boxes are padded, so the boxes of neighbouring
# lines can overlap - most noticeably for rotated text - which makes selecting a single
# line in a viewer pick up parts of the adjacent one. Shrinking the glyph height a
# little, and centring it in the line box, keeps the selectable areas apart.
TEXT_HEIGHT_RATIO = 0.8


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

    def l(self, x: float, y: float):  # noqa: E743 (mirrors the PDF "l" operator)
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


def _text_tm(font_size: float, cos_a: float, sin_a: float, x: float, y: float):
    """Text matrix for a run of the given size, advance direction and origin.

    The text advances along `(cos_a, sin_a)` and the glyphs rise perpendicular to
    it, so vertical text is just a run whose advance direction points down the page.
    """
    return (
        font_size * cos_a,
        font_size * sin_a,
        -font_size * sin_a,
        font_size * cos_a,
        x,
        y,
    )


def _stretch(width: float, nchars: int, font_size: float) -> float:
    """Horizontal scaling (Tz) that makes `nchars` glyphs span `width`."""
    return 100.0 * width / nchars / font_size * CHAR_ASPECT


def _word_runs(
    children: Iterable[Textbox],
    scale: tuple[float, float],
    height: int,
    font_size: float,
    cos_a: float,
    sin_a: float,
    ox: float,
    oy: float,
):
    """Lay out the words of a segmented (space-delimited) line on the line's baseline.

    Each word keeps its own position along the line and its own width, but the angle,
    the font size and the baseline (the line's own origin `(ox, oy)`) are taken from
    the line, so the rendered text does not wobble from word to word. The word origin
    is obtained by projecting the word's lower-left corner onto the line baseline,
    which drops the perpendicular jitter of the individual word boxes.
    """

    def run(t: float, width: float, text: str):
        """Build a run starting at distance `t` along the baseline."""
        return (
            _text_tm(font_size, cos_a, sin_a, ox + t * cos_a, oy + t * sin_a),
            _stretch(width, len(text), font_size),
            text,
        )

    words = []
    for word in children:
        wtext = word.text.strip()
        wbb = word.bb
        wwidth = wbb.true_width() * scale[0]
        if len(wtext) == 0 or wwidth <= 0:
            continue
        wx = wbb.ll.x * scale[0]
        wy = (height - wbb.ll.y) * scale[1]
        words.append(((wx - ox) * cos_a + (wy - oy) * sin_a, wwidth, wtext))

    runs = []
    min_space = font_size * MIN_SPACE_RATIO
    for i, (t, wwidth, wtext) in enumerate(words):
        if i + 1 < len(words):
            # Fill the gap up to the next word with an explicit space, so that text
            # extractors do not have to infer the word separation from the glyph
            # positions alone. The reported word boxes are padded and may even touch,
            # so trim the word to keep room for a space that actually advances the
            # text position; text laid out strictly left to right also keeps
            # extractors from mistaking a word for the start of a new line.
            span = words[i + 1][0] - t
            if span > 0:
                wwidth = min(wwidth, max(span - min_space, span / 2.0))
            runs.append(run(t, wwidth, wtext))
            runs.append(run(t + wwidth, max(span - wwidth, min_space), " "))
        else:
            runs.append(run(t, wwidth, wtext))
    return runs


def _draw_box(bbox, scale: tuple[float, float], height: int, rgb: tuple[float, float, float]):
    """Stroke the outline of a bounding box, for debugging."""
    corners = (bbox.ul, bbox.ur, bbox.lr, bbox.ll)
    cs = ContentStreamBuilder().q().RG(*rgb).w(0.75)
    for i, p in enumerate(corners):
        x = p.x * scale[0]
        y = (height - p.y) * scale[1]
        cs = cs.m(x, y) if i == 0 else cs.l(x, y)
    return cs.h().S().Q()


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

        if len(text) == 0 or box_width <= 0 or box_height <= 0:
            continue

        vertical = result.is_vertical
        # Direction the text advances in: to the right along the baseline for
        # horizontal text, down the column for vertical text.
        angle = -bbox.writing_angle(vertical)  # PDF coordinate is y-up, so negate
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        # Vertical text starts at the top of its column, horizontal text at the left
        # end of its baseline. The glyphs rise perpendicular to the advance direction
        # from there, so move the origin half of what they lost to the shrinking,
        # which centres them in the line box.
        line_thickness = box_width if vertical else box_height
        font_size = line_thickness * TEXT_HEIGHT_RATIO
        inset = (line_thickness - font_size) / 2.0
        anchor = bbox.ul if vertical else bbox.ll
        ox = anchor.x * scale[0] - inset * sin_a
        oy = (height - anchor.y) * scale[1] + inset * cos_a

        log.debug(
            f"Textline '{text}' bbox (in px): {bbox} vertical: {vertical}, angle: {angle}, "
            f"box_width: {box_width}, box_height: {box_height}"
        )

        word_boxes = []
        if vertical:
            runs = [
                (
                    _text_tm(font_size, cos_a, sin_a, ox, oy),
                    _stretch(box_height, len(text), font_size),
                    text,
                )
            ]
        else:
            runs = []
            if result.children:
                # Word-level rendering for languages written with word separators.
                runs = _word_runs(result.children, scale, height, font_size, cos_a, sin_a, ox, oy)
                word_boxes = [word.bb for word in result.children]
            if not runs:
                runs = [
                    (
                        _text_tm(font_size, cos_a, sin_a, ox, oy),
                        _stretch(box_width, len(text), font_size),
                        text,
                    )
                ]

        cs_line = (
            ContentStreamBuilder()
            .BT()
            .BDC(Name.Span, n)
            .Tr(3)  # Invisible ink
            .Tf(FONT_NAME, 1)
        )
        for tm_args, stretch, run_text in runs:
            cs_line = cs_line.Tm(*tm_args).Tz(stretch).TJ(run_text)
        cs = cs.add(cs_line.EMC().ET())

        if boxes:
            cs = cs.add(_draw_box(bbox, scale, height, (1.0, 0.0, 0.0)))
            if TEXT_POSITION_DEBUG:
                for wbb in word_boxes:
                    cs = cs.add(_draw_box(wbb, scale, height, (0.0, 0.0, 1.0)))

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
