import logging
import math
from typing import NamedTuple

log = logging.getLogger(__name__)


class Point(NamedTuple):
    """Represents a point in 2D space. (upper-left origin, pixel coordinates)"""

    x: int
    y: int


def distance(p1: Point, p2: Point) -> float:
    return math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)


class BoundingBox(NamedTuple):
    """Represents a bounding box in the document."""

    ul: Point
    ur: Point
    ll: Point
    lr: Point

    def to_hocr_bbox(self) -> str:
        return f"bbox {self.ul.x} {self.ul.y} {self.lr.x} {self.lr.y}"

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

    def angle(self) -> float:
        """Returns the angle of the bounding box in radians."""
        delta_x = self.ur.x - self.ul.x
        delta_y = self.ur.y - self.ul.y
        return math.atan2(delta_y, delta_x)


class Textbox(NamedTuple):
    """Represents a text box in the document."""

    text: str
    bb: BoundingBox
    confidence: int  # 0-100
    is_vertical: bool


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

locale_to_lang_code = {v: k for k, v in lang_code_to_locale.items()}
