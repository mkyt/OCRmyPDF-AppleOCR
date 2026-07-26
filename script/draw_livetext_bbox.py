#!/usr/bin/env python3
"""Debug tool: run the LiveText (VKCImageAnalyzer) engine on a PDF and overlay
the recognized bounding boxes as polygons on top of the original pages.

Unlike `draw_text_bbox.py`, which recovers boxes from the *text layer* of an
already-OCRed PDF, this script talks to `ocrmypdf_appleocr.livetext` directly:
each page is rasterized with Quartz, handed to VKCImageAnalyzer, and every
recognized line (and, at word level, every word within it) is stroked as a
closed quad. The quads are drawn as true polygons rather than axis-aligned
rectangles, so rotated/skewed recognition results stay visible as such.

Boxes come back from the analyzer in image pixels with an upper-left origin;
they are mapped back to the page's own user space through the inverse of the
Quartz drawing transform, which also undoes the page's /Rotate and any
CropBox offset, and appended to the page content stream (i.e. drawn last, on
top of the page image).

Usage:
    uv run script/draw_livetext_bbox.py input.pdf output.pdf
    uv run script/draw_livetext_bbox.py input.pdf output.pdf -l jpn --dpi 400
    uv run script/draw_livetext_bbox.py input.pdf output.pdf --level word
    uv run script/draw_livetext_bbox.py in.pdf out.pdf --pages 1,3-5 --save-images ./tmp
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pikepdf
import Quartz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draw_text_bbox import stroke_instructions  # noqa: E402
from ocrmypdf_appleocr.common import (  # noqa: E402
    Textbox,
    lang_code_to_locale,
    unsegmented_languages,
)
from ocrmypdf_appleocr.livetext import (  # noqa: E402
    livetext_supported,
    ocr_VKCImageAnalyzerRequest,
)

Point = tuple[float, float]
Quad = list[Point]
# pixel (upper-left origin) -> PDF user space
PixelToUser = Callable[[float, float], Point]

LINE_COLOR = (1.0, 0.0, 0.0)  # red
WORD_COLOR = (0.0, 0.0, 1.0)  # blue


def cfurl(path: Path):
    return Quartz.CFURLCreateWithFileSystemPath(
        None, str(path.resolve()), Quartz.kCFURLPOSIXPathStyle, False
    )


def render_page(page, png_path: Path, dpi: float) -> tuple[int, int, PixelToUser]:
    """Rasterize one CGPDFPage to `png_path`.

    Returns the pixel size of the image and a function mapping a pixel
    coordinate (upper-left origin, as the analyzer reports them) back to the
    page's PDF user space.
    """
    box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFCropBox)
    width_pt, height_pt = box.size.width, box.size.height
    if Quartz.CGPDFPageGetRotationAngle(page) % 180 == 90:
        # The drawing transform below turns the page upright, so the image is
        # as wide as the page is tall for a quarter-turned page.
        width_pt, height_pt = height_pt, width_pt

    scale = dpi / 72.0
    width = max(1, round(width_pt * scale))
    height = max(1, round(height_pt * scale))
    # Recomputed from the rounded pixel size, so the mapping back to user
    # space matches the image the analyzer actually saw.
    sx, sy = width / width_pt, height / height_pt

    # Maps user space onto the upright page rect, applying /Rotate and the
    # CropBox offset.
    transform = Quartz.CGPDFPageGetDrawingTransform(
        page, Quartz.kCGPDFCropBox, Quartz.CGRectMake(0, 0, width_pt, height_pt), 0, True
    )

    ctx = Quartz.CGBitmapContextCreate(
        None,
        width,
        height,
        8,
        0,
        Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGImageAlphaNoneSkipLast,
    )
    if ctx is None:
        raise RuntimeError(f"Could not create a {width}x{height} bitmap context")
    # PDF pages are transparent where nothing is painted; OCR wants paper.
    Quartz.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, width, height))
    Quartz.CGContextScaleCTM(ctx, sx, sy)
    Quartz.CGContextConcatCTM(ctx, transform)
    Quartz.CGContextDrawPDFPage(ctx, page)

    image = Quartz.CGBitmapContextCreateImage(ctx)
    dest = Quartz.CGImageDestinationCreateWithURL(cfurl(png_path), "public.png", 1, None)
    if dest is None:
        raise RuntimeError(f"Could not write {png_path}")
    Quartz.CGImageDestinationAddImage(dest, image, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        raise RuntimeError(f"Could not write {png_path}")

    inverse = Quartz.CGAffineTransformInvert(transform)

    def to_user(px: float, py: float) -> Point:
        # Bitmap contexts have a lower-left origin, the analyzer an upper-left one.
        p = Quartz.CGPointApplyAffineTransform(
            Quartz.CGPointMake(px / sx, (height - py) / sy), inverse
        )
        return (p.x, p.y)

    return width, height, to_user


def textbox_quad(textbox: Textbox, to_user: PixelToUser) -> Quad:
    bb = textbox.bb
    return [to_user(p.x, p.y) for p in (bb.ul, bb.ur, bb.lr, bb.ll)]


def collect_quads(
    textboxes: list[Textbox], to_user: PixelToUser, draw_lines: bool, draw_words: bool
) -> tuple[list[Quad], list[Quad]]:
    line_quads: list[Quad] = []
    word_quads: list[Quad] = []
    for line in textboxes:
        if draw_lines:
            line_quads.append(textbox_quad(line, to_user))
        if draw_words:
            for word in line.children or []:
                if word.text.strip():
                    word_quads.append(textbox_quad(word, to_user))
    return line_quads, word_quads


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    """Parse a `1,3-5` style page selection into 0-based page indices."""
    if not spec:
        return list(range(page_count))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        first, _, last = part.partition("-")
        start = int(first)
        end = int(last) if last else start
        if not 1 <= start <= end <= page_count:
            raise ValueError(f"Page range '{part}' is out of bounds (1-{page_count})")
        pages.extend(range(start - 1, end))
    return pages


def annotate(
    input_pdf: Path,
    output_pdf: Path,
    locales: list[str],
    unit: str,
    draw_lines: bool,
    draw_words: bool,
    dpi: float,
    line_width: float,
    page_spec: str | None,
    save_images: Path | None,
    verbose: bool,
) -> tuple[int, int]:
    """OCR each selected page and stroke the recognized boxes onto it.

    Returns the total number of line and word boxes drawn.
    """
    document = Quartz.CGPDFDocumentCreateWithURL(cfurl(input_pdf))
    if document is None:
        raise RuntimeError(f"Could not open {input_pdf} as a PDF")

    if save_images is not None:
        save_images.mkdir(parents=True, exist_ok=True)

    total_lines = total_words = 0
    tmp_pdf = output_pdf.with_name(output_pdf.name + ".tmp")

    with pikepdf.open(input_pdf) as pdf, tempfile.TemporaryDirectory() as tmpdir:
        page_indices = parse_pages(page_spec, len(pdf.pages))
        for index in page_indices:
            image_dir = save_images if save_images is not None else Path(tmpdir)
            png_path = image_dir / f"{input_pdf.stem}_p{index + 1:04d}.png"
            width, height, to_user = render_page(
                Quartz.CGPDFDocumentGetPage(document, index + 1), png_path, dpi
            )

            textboxes = ocr_VKCImageAnalyzerRequest(png_path, width, height, locales, unit)
            line_quads, word_quads = collect_quads(textboxes, to_user, draw_lines, draw_words)
            total_lines += len(line_quads)
            total_words += len(word_quads)
            print(
                f"page {index + 1}: {width}x{height} px, "
                f"{len(line_quads)} line box(es), {len(word_quads)} word box(es)",
                file=sys.stderr,
            )
            if verbose:
                for line in textboxes:
                    print(f"  line: {line.text!r}", file=sys.stderr)
                    for word in line.children or []:
                        print(f"    word: {word.text!r}", file=sys.stderr)

            if not line_quads and not word_quads:
                continue
            page = pdf.pages[index]
            instructions = list(pikepdf.parse_content_stream(page))
            # Appended last, so the overlay is painted over the page image.
            instructions += stroke_instructions(line_quads, LINE_COLOR, line_width)
            instructions += stroke_instructions(word_quads, WORD_COLOR, line_width)
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions))

        pdf.save(tmp_pdf)
    tmp_pdf.replace(output_pdf)

    return total_lines, total_words


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the LiveText OCR engine on a PDF and overlay the recognized "
            "line/word bounding boxes as polygons, for debugging recognition "
            "geometry."
        )
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument(
        "-l",
        "--lang",
        action="append",
        default=None,
        metavar="LANG",
        help=(
            "Language of the document, as a tesseract-style code (eng, jpn, ...) "
            "or a locale (en-US); repeatable (default: eng)"
        ),
    )
    parser.add_argument(
        "--level",
        choices=("line", "word", "both"),
        default="both",
        help=(
            "Which boxes to draw: recognition lines (red), the words within "
            "them (blue), or both (default)"
        ),
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=300.0,
        help="Resolution the pages are rasterized at before OCR (default: 300)",
    )
    parser.add_argument(
        "--line-width",
        type=float,
        default=0.5,
        help="Stroke line width in PDF units (default: 0.5)",
    )
    parser.add_argument(
        "--pages",
        default=None,
        metavar="SPEC",
        help="Only OCR these 1-based pages, e.g. '1,3-5' (default: all)",
    )
    parser.add_argument(
        "--save-images",
        type=Path,
        default=None,
        metavar="DIR",
        help="Keep the rasterized page images in DIR instead of a temporary directory",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print the recognized text of every line and word",
    )
    args = parser.parse_args()

    if not livetext_supported:
        print("LiveText requires macOS 13 (Ventura) or later.", file=sys.stderr)
        return 1

    languages = args.lang or ["eng"]
    locales = [lang_code_to_locale.get(lang, lang) for lang in languages]

    # Mirrors ocrmypdf_appleocr.perform_ocr: VisionKit does not segment words
    # for languages that are not written with spaces, so only ask for lines.
    unit = "word" if args.level in ("word", "both") else "line"
    if unit == "word" and any(lang in unsegmented_languages for lang in languages):
        print(
            f"Note: {'/'.join(languages)} is not word-segmented by LiveText; "
            "drawing line boxes only.",
            file=sys.stderr,
        )
        unit = "line"
        args.level = "line"

    lines, words = annotate(
        args.input_pdf,
        args.output_pdf,
        locales=locales,
        unit=unit,
        draw_lines=args.level in ("line", "both"),
        draw_words=args.level in ("word", "both"),
        dpi=args.dpi,
        line_width=args.line_width,
        page_spec=args.pages,
        save_images=args.save_images,
        verbose=args.verbose,
    )

    print(f"Drew {lines} line and {words} word box(es). Wrote {args.output_pdf}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
