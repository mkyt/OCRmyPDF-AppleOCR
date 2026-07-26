#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pikepdf>=8.10.1"]
# ///
"""Debug tool: outline the text in a PDF's content stream(s) with a red
rectangle, either one box per BT..ET text object (default) or one per
text-showing run with `--level word`.

Phantom-text PDFs produced by OCRmyPDF-AppleOCR embed invisible text (Tr 3)
inside `BT ... ET` blocks, often inside a Form XObject that is painted onto
the page via the `Do` operator (typically *before* the page image, which
would otherwise cover any markup drawn inside that Form). This script walks
every content stream (the page's own, and any Form XObject reachable via
`Do`), replays the text positioning operators (Td/TD/Tm/T*, Tf, Tc/Tw/Tz/Ts,
Tj/TJ/'/") to compute the bounding box actually produced by each BT..ET
block, and appends a stroked red rectangle for it to the *page's* own
content stream, so the outline is drawn last and stays visible on top.

Usage:
    uv run script/draw_text_bbox.py input.pdf output.pdf
    uv run script/draw_text_bbox.py input.pdf output.pdf --color 0 0 1 --line-width 1
    uv run script/draw_text_bbox.py input.pdf output.pdf --level word
"""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]
Quad = list[Point]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def translate(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def mat_mult(a: Matrix, b: Matrix) -> Matrix:
    """Compose two PDF matrices: apply `a` first, then `b`."""
    a0, a1, a2, a3, a4, a5 = a
    b0, b1, b2, b3, b4, b5 = b
    return (
        a0 * b0 + a1 * b2,
        a0 * b1 + a1 * b3,
        a2 * b0 + a3 * b2,
        a2 * b1 + a3 * b3,
        a4 * b0 + a5 * b2 + b4,
        a4 * b1 + a5 * b3 + b5,
    )


def mat_apply(m: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def mat_invert(m: Matrix) -> Matrix | None:
    """Invert a PDF matrix, or return None if it is (numerically) singular,
    e.g. a zero font size."""
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-9:
        return None
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))


def quad_area(quad: Quad) -> float:
    """Shoelace formula."""
    area = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(quad, quad[1:] + quad[:1])
    )
    return abs(area) / 2.0


@dataclass
class FontMetrics:
    """The few font metrics we need, in text space (glyph space / 1000)."""

    is_cid: bool = False
    widths: dict[int, float] = field(default_factory=dict)
    default_width: float = 0.5
    ascent: float = 0.8
    descent: float = -0.2

    def width(self, code: int) -> float:
        return self.widths.get(code, self.default_width)


def milli(font_dict, key: str, default: float) -> float:
    """Read a glyph-space (/1000) entry from a font dict as a text-space value."""
    if font_dict is None or key not in font_dict:
        return default
    return float(font_dict[key]) / 1000.0


def parse_w_array(w_array) -> dict[int, float]:
    """Parse a Type0 descendant font's /W array into {cid: width/1000}.

    Entries come in two shapes: `first [w1 w2 ...]` (one width per
    consecutive CID) and `first last w` (a CID range sharing one width).
    """
    widths: dict[int, float] = {}
    items = list(w_array)
    i = 0
    while i < len(items) - 1:
        c_first = int(items[i])
        try:
            run = list(items[i + 1])
        except TypeError:
            c_last, w = int(items[i + 1]), float(items[i + 2]) / 1000.0
            widths.update((cid, w) for cid in range(c_first, c_last + 1))
            i += 3
        else:
            widths.update(
                (c_first + offset, float(w) / 1000.0) for offset, w in enumerate(run)
            )
            i += 2
    return widths


def load_font_metrics(font_dict) -> FontMetrics:
    if font_dict is None:
        return FontMetrics()

    is_cid = str(font_dict.get("/Subtype", "")) == "/Type0"
    if is_cid:
        # A Type0 font's widths and descriptor live on its descendant font.
        descendants = font_dict.get("/DescendantFonts")
        metrics = descendants[0] if descendants else None
        widths = parse_w_array(metrics["/W"]) if metrics and "/W" in metrics else {}
    else:
        metrics = font_dict
        first_char = int(font_dict.get("/FirstChar", 0))
        widths = {
            first_char + offset: float(w) / 1000.0
            for offset, w in enumerate(font_dict.get("/Widths", []))
        }

    descriptor = metrics.get("/FontDescriptor") if metrics is not None else None
    return FontMetrics(
        is_cid=is_cid,
        widths=widths,
        default_width=(
            milli(metrics, "/DW", 1.0) if is_cid else milli(descriptor, "/MissingWidth", 0.5)
        ),
        ascent=milli(descriptor, "/Ascent", 0.8),
        descent=milli(descriptor, "/Descent", -0.2),
    )


def as_text_bytes(operand) -> bytes | None:
    """Return the raw bytes of a string operand, or None if it's numeric."""
    try:
        return bytes(operand)
    except TypeError:
        return None


def char_codes(data: bytes, is_cid: bool) -> list[int]:
    """Character codes of one string operand (two bytes per code for a CID font)."""
    if is_cid:
        return [(data[i] << 8) | data[i + 1] for i in range(0, len(data) - 1, 2)]
    return list(data)


@dataclass
class GraphicsState:
    ctm: Matrix = IDENTITY
    font: FontMetrics | None = None
    font_size: float = 1.0
    tc: float = 0.0  # character spacing
    tw: float = 0.0  # word spacing
    tz: float = 100.0  # horizontal scaling, in percent
    tl: float = 0.0  # leading
    ts: float = 0.0  # text rise


class TextQuadFinder:
    """Replays a content stream's operators to find text bounding quads,
    recursing into any Form XObjects it paints.

    At the "line" level each BT..ET text object yields one quad. At the "word"
    level every text-showing operator yields its own quad instead, which is what
    shows the word boxes of a word-level OCR text layer: those are written as one
    BT..ET block per line holding one Tm/Tz/TJ run per word (see
    ocrmypdf_appleocr/pdf.py). Runs that draw nothing but spaces are skipped, so
    the gaps between words stay unmarked.
    """

    def __init__(self, level: str = "line"):
        # Quads (4 corner points each) found anywhere in the page (including
        # inside Form XObjects painted via `Do`), already transformed into
        # the page's own absolute content-stream coordinate space.
        self.quads: list[Quad] = []
        self.visited: set = set()
        self.level = level

    def process(self, instructions, resources, base_ctm: Matrix) -> None:
        """Replay operators from one content stream.

        `base_ctm` maps this stream's own local coordinate space (where its
        `cm`/`q`/`Q` operators start from identity) into the top-level
        page's absolute content-stream space, so that boxes found while
        recursing into Form XObjects can be reported in page coordinates.
        """
        gs = GraphicsState()
        stack: list[GraphicsState] = []
        tm = tlm = IDENTITY
        font_cache: dict[str, FontMetrics] = {}

        # A BT..ET block is treated as one rigid, unrotated "line" of text:
        # BT resets Tm/Tlm to identity, Td/TD only ever translate (they
        # can't change Tm's rotation/scale part), and `cm`/`q`/`Q` aren't
        # valid between BT and ET per the PDF spec, so the CTM can't change
        # mid-block either. That means every text-showing operator in a
        # block shares the same orientation, established by whichever
        # operator (Tm, or the block's initial identity Tm) is in effect at
        # the first Tj/TJ/'/" call. We track the block's bounding box in
        # that orientation's own (u, v) coordinates and only convert back to
        # a device-space quad at ET, instead of collapsing to an
        # axis-aligned box early -- which would lose the rotation applied
        # via Tm (see ocrmypdf_appleocr/pdf.py's rotated Tm construction).
        block: Matrix | None = None  # text space -> device space, at first show
        block_inv: Matrix | None = None
        block_uv: tuple[float, float, float, float] | None = None

        fonts = resources.get("/Font") if resources else None
        xobjects = resources.get("/XObject") if resources else None

        def get_font(name: str) -> FontMetrics:
            if name not in font_cache:
                font_cache[name] = load_font_metrics(fonts.get(name) if fonts else None)
            return font_cache[name]

        def move_text(tx: float, ty: float) -> None:
            nonlocal tm, tlm
            tlm = mat_mult(translate(tx, ty), tlm)
            tm = tlm

        def advance(elements) -> float:
            """Total horizontal displacement of one text-showing operator."""
            th = gs.tz / 100.0
            total_tx = 0.0
            for el in elements:
                data = as_text_bytes(el)
                if data is None:  # a TJ kerning adjustment, in 1/1000 text units
                    total_tx -= float(el) / 1000.0 * gs.font_size * th
                    continue
                for code in char_codes(data, gs.font.is_cid):
                    word_spacing = gs.tw if (not gs.font.is_cid and code == 32) else 0.0
                    total_tx += (gs.font.width(code) * gs.font_size + gs.tc + word_spacing) * th
            return total_tx

        def is_blank(elements) -> bool:
            """True if a text-showing operator draws nothing but spaces."""
            saw_text = False
            for el in elements:
                data = as_text_bytes(el)
                if data is None:
                    continue
                saw_text = True
                if any(code != 32 for code in char_codes(data, gs.font.is_cid)):
                    return False
            return saw_text

        def add_quad(to_page: Matrix, x_end: float) -> None:
            y_lo = gs.ts + gs.font.descent * gs.font_size
            y_hi = gs.ts + gs.font.ascent * gs.font_size
            quad = [
                mat_apply(to_page, x, y)
                for x, y in ((0.0, y_lo), (0.0, y_hi), (x_end, y_hi), (x_end, y_lo))
            ]
            if quad_area(quad) >= 1e-6:
                self.quads.append(quad)

        def show_text(elements) -> None:
            nonlocal tm, block, block_inv, block_uv
            if gs.font is None:
                return
            total_tx = advance(elements)
            full = mat_mult(tm, gs.ctm)

            if self.level == "word":
                # One quad per run, in the run's own orientation.
                if not is_blank(elements):
                    add_quad(mat_mult(full, base_ctm), total_tx)
                tm = mat_mult(translate(total_tx, 0.0), tm)
                return

            if block is None:
                block, block_inv = full, mat_invert(full)

            if block_inv is not None:
                # Corners of this run's box, in the block's own orientation.
                to_block = mat_mult(full, block_inv)
                y_lo = gs.ts + gs.font.descent * gs.font_size
                y_hi = gs.ts + gs.font.ascent * gs.font_size
                corners = [
                    mat_apply(to_block, x, y)
                    for x, y in ((0.0, y_lo), (0.0, y_hi), (total_tx, y_hi), (total_tx, y_lo))
                ]
                us = [u for u, _ in corners]
                vs = [v for _, v in corners]
                if block_uv is not None:
                    u_min, v_min, u_max, v_max = block_uv
                    us += [u_min, u_max]
                    vs += [v_min, v_max]
                block_uv = (min(us), min(vs), max(us), max(vs))

            tm = mat_mult(translate(total_tx, 0.0), tm)

        def end_block() -> None:
            nonlocal block, block_inv, block_uv
            if block_uv is not None:
                u_min, v_min, u_max, v_max = block_uv
                # Transform each corner individually (rather than reducing to
                # an axis-aligned box) so any rotation carried by the block
                # matrix or by `base_ctm` is preserved.
                to_page = mat_mult(block, base_ctm)
                quad = [
                    mat_apply(to_page, u, v)
                    for u, v in ((u_min, v_min), (u_min, v_max), (u_max, v_max), (u_max, v_min))
                ]
                if quad_area(quad) >= 1e-6:
                    self.quads.append(quad)
            block = block_inv = block_uv = None

        for instr in instructions:
            op = str(instr.operator)
            operands = instr.operands

            if op == "q":
                stack.append(copy.copy(gs))
            elif op == "Q":
                if stack:
                    gs = stack.pop()
            elif op == "cm":
                gs.ctm = mat_mult(tuple(float(v) for v in operands), gs.ctm)
            elif op == "BT":
                tm = tlm = IDENTITY
                block = block_inv = block_uv = None
            elif op == "ET":
                end_block()
            elif op == "Tf":
                gs.font = get_font(str(operands[0]))
                gs.font_size = float(operands[1])
            elif op == "Tc":
                gs.tc = float(operands[0])
            elif op == "Tw":
                gs.tw = float(operands[0])
            elif op == "Tz":
                gs.tz = float(operands[0])
            elif op == "TL":
                gs.tl = float(operands[0])
            elif op == "Ts":
                gs.ts = float(operands[0])
            elif op == "Td":
                move_text(float(operands[0]), float(operands[1]))
            elif op == "TD":
                gs.tl = -float(operands[1])
                move_text(float(operands[0]), float(operands[1]))
            elif op == "Tm":
                tm = tlm = tuple(float(v) for v in operands)
            elif op == "T*":
                move_text(0.0, -gs.tl)
            elif op == "Tj":
                show_text([operands[0]])
            elif op == "TJ":
                show_text(list(operands[0]))
            elif op == "'":
                move_text(0.0, -gs.tl)
                show_text([operands[0]])
            elif op == '"':
                gs.tw, gs.tc = float(operands[0]), float(operands[1])
                move_text(0.0, -gs.tl)
                show_text([operands[2]])
            elif op == "Do":
                xobj = xobjects.get(str(operands[0])) if xobjects else None
                if xobj is not None and str(xobj.get("/Subtype", "")) == "/Form":
                    self._process_form(xobj, resources, gs.ctm, base_ctm)

    def _process_form(self, xobj, parent_resources, ctm_at_do: Matrix, base_ctm: Matrix) -> None:
        if xobj.objgen in self.visited:
            return
        self.visited.add(xobj.objgen)

        # A Form XObject's own /Matrix is applied (in addition to the CTM in
        # effect at the `Do` call) before its content stream runs.
        form_matrix = tuple(float(v) for v in xobj["/Matrix"]) if "/Matrix" in xobj else IDENTITY
        # Resources are inherited from the invoking context if the Form
        # doesn't declare its own (per the PDF spec's resource lookup rules).
        self.process(
            pikepdf.parse_content_stream(xobj),
            xobj.get("/Resources") or parent_resources,
            mat_mult(form_matrix, mat_mult(ctm_at_do, base_ctm)),
        )


def stroke_instructions(quads: list[Quad], color, line_width: float) -> list:
    """Content-stream instructions stroking each quad as a closed polygon."""
    op = pikepdf.Operator
    csi = pikepdf.ContentStreamInstruction
    instrs = []
    for (x0, y0), *rest in quads:
        instrs.extend(
            [
                csi([], op("q")),
                csi(list(color), op("RG")),
                csi([line_width], op("w")),
                csi([x0, y0], op("m")),
                *(csi([x, y], op("l")) for x, y in rest),
                csi([], op("h")),
                csi([], op("S")),
                csi([], op("Q")),
            ]
        )
    return instrs


def draw_text_bboxes(
    pdf: pikepdf.Pdf,
    box_color=(1.0, 0.0, 0.0),
    line_width: float = 0.5,
    level: str = "line",
) -> int:
    """Outline every text object on every page with a stroked rectangle,
    one per BT..ET block ("line") or one per text-showing run ("word").
    Returns the number of boxes drawn."""
    total = 0
    for page in pdf.pages:
        finder = TextQuadFinder(level=level)
        instructions = pikepdf.parse_content_stream(page)
        finder.process(instructions, page.get("/Resources"), IDENTITY)
        if not finder.quads:
            continue
        total += len(finder.quads)
        page.Contents = pdf.make_stream(
            pikepdf.unparse_content_stream(
                list(instructions) + stroke_instructions(finder.quads, box_color, line_width)
            )
        )
    return total


def annotate_pdf_file(
    input_pdf,
    output_pdf=None,
    box_color=(1.0, 0.0, 0.0),
    line_width: float = 0.5,
    level: str = "line",
) -> int:
    """Open `input_pdf`, draw a box around every text object, and
    save the result to `output_pdf` (defaults to `input_pdf`, i.e. in-place).

    The result is always written to a temporary file next to the destination
    and renamed into place, so annotating in place is safe.

    Returns the number of boxes drawn.
    """
    output_pdf = Path(output_pdf) if output_pdf is not None else Path(input_pdf)
    tmp_path = output_pdf.with_name(output_pdf.name + ".tmp")

    with pikepdf.open(input_pdf) as pdf:
        count = draw_text_bboxes(pdf, box_color=box_color, line_width=line_width, level=level)
        pdf.save(tmp_path)
    tmp_path.replace(output_pdf)

    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Outline each BT..ET phantom-text block in a PDF's content "
            "stream(s) with a stroked rectangle, for debugging OCR text "
            "placement."
        )
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument(
        "--color",
        type=float,
        nargs=3,
        metavar=("R", "G", "B"),
        default=(1.0, 0.0, 0.0),
        help="Stroke color as three 0-1 floats (default: 1 0 0, i.e. red)",
    )
    parser.add_argument(
        "--line-width",
        type=float,
        default=0.5,
        help="Stroke line width in PDF units (default: 0.5)",
    )
    parser.add_argument(
        "--level",
        choices=("line", "word"),
        default="line",
        help=(
            "Outline whole BT..ET blocks (default) or each text-showing run "
            "within them, which is one word in a word-level OCR text layer"
        ),
    )
    args = parser.parse_args()

    count = annotate_pdf_file(
        args.input_pdf,
        args.output_pdf,
        box_color=tuple(args.color),
        line_width=args.line_width,
        level=args.level,
    )

    print(f"Drew {count} bounding box(es). Wrote {args.output_pdf}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
