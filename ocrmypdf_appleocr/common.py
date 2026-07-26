import logging
import math
from typing import NamedTuple

log = logging.getLogger(__name__)


class Point(NamedTuple):
    """Represents a point in 2D space. (upper-left origin, pixel coordinates)

    Kept as floats: the OCR engines report corners in normalized coordinates, and
    quantising them to whole pixels on the way in throws away precision that the
    renderers cannot get back. Rounding belongs at the output boundary, i.e. in
    `BoundingBox.to_hocr_bbox`.
    """

    x: float
    y: float


def distance(p1: Point, p2: Point) -> float:
    return math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)


def _edge_angle(p1: Point, p2: Point) -> float:
    """Direction of the edge from `p1` to `p2`, in radians."""
    return math.atan2(p2.y - p1.y, p2.x - p1.x)


def _mean_angle(a1: float, a2: float) -> float:
    """Mean of two angles, averaged the short way around the circle."""
    return a1 + math.remainder(a2 - a1, 2 * math.pi) / 2.0


class BoundingBox(NamedTuple):
    """Represents a bounding box in the document."""

    ul: Point
    ur: Point
    ll: Point
    lr: Point

    def to_hocr_bbox(self) -> str:
        # hOCR bboxes are whole pixels, so this is where the coordinates get rounded.
        return f"bbox {round(self.ul.x)} {round(self.ul.y)} {round(self.lr.x)} {round(self.lr.y)}"

    def estimated_baseline(self) -> str:
        intercept = max(self.ll.y, self.lr.y) - self.lr.y
        slope = (
            (self.lr.y - self.ll.y) / (self.lr.x - self.ll.x) if (self.lr.x - self.ll.x) != 0 else 0
        )
        return f"baseline {slope} {intercept}"

    def true_width(self) -> float:
        """Returns the true width of the bounding box."""
        return (distance(self.ul, self.ur) + distance(self.ll, self.lr)) / 2.0

    def true_height(self) -> float:
        """Returns the true height of the bounding box."""
        return (distance(self.ul, self.ll) + distance(self.ur, self.lr)) / 2.0

    def writing_angle(self, vertical: bool) -> float:
        """Returns the angle the text advances along, in radians.

        Only the two edges that run *along* the text are used: the top and bottom
        edges for horizontal text, the left and right ones for vertical text. The
        perpendicular edges are just one line tall, so rounding the reported corners
        to whole pixels tilts them by up to a degree; orienting a line by that error
        walks its far end right out of the line box, which is what makes selecting
        such a line in a viewer grab the neighbouring one.
        """
        if vertical:
            return _mean_angle(_edge_angle(self.ul, self.ll), _edge_angle(self.ur, self.lr))
        return _mean_angle(_edge_angle(self.ul, self.ur), _edge_angle(self.ll, self.lr))


class Textbox(NamedTuple):
    """Represents a text box in the document."""

    text: str
    bb: BoundingBox
    confidence: int  # 0-100
    is_vertical: bool
    children: "list[Textbox] | None"


lang_code_to_locale = {
    "eng": "en-US",
    "fra": "fr-FR",
    "ita": "it-IT",
    "deu": "de-DE",
    "spa": "es-ES",
    "por": "pt-BR",
    "chi_sim": "zh-Hans",
    "chi_tra": "zh-Hant",
    "yue_sim": "yue-Hans",
    "yue_tra": "yue-Hant",
    "kor": "ko-KR",
    "jpn": "ja-JP",
    "rus": "ru-RU",
    "ukr": "uk-UA",
    "tha": "th-TH",
    "vie": "vi-VT",
    "ara": "ar-SA",
    "ars": "ars-SA",
    "tur": "tr-TR",
    "ind": "id-ID",
    "ces": "cs-CZ",
    "dan": "da-DK",
    "nld": "nl-NL",
    "nor": "no-NO",
    "nno": "nn-NO",
    "nob": "nb-NO",
    "msa": "ms-MY",
    "pol": "pl-PL",
    "ron": "ro-RO",
    "swe": "sv-SE",
}

unsegmented_languages = set(["chi_sim", "chi_tra", "yue_sim", "yue_tra", "jpn", "tha"])


locale_to_lang_code = {v: k for k, v in lang_code_to_locale.items()}


def is_undetermined_language(options) -> bool:
    if options.languages and len(options.languages) == 1 and options.languages[0] == "und":
        return True
    return False
