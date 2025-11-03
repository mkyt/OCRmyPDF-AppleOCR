import logging

log = logging.getLogger(__name__)
from typing import NamedTuple


class Textbox(NamedTuple):
    """Represents a text box in the document. (bounding box is in image pixel coordinates)"""

    text: str
    x: int
    y: int
    w: int
    h: int
    confidence: int  # 0-100


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

lang_code_two_letter_to_three_letter = {
    "en": "eng",
    "fr": "fra",
    "it": "ita",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "zh-cn": "chi_sim",
    "zh-tw": "chi_tra",
    "ko": "kor",
    "ja": "jpn",
    "ru": "rus",
    "uk": "ukr",
    "th": "tha",
    "vi": "vie",
    "ar": "ara",
    "tr": "tur",
    "id": "ind",
    "cs": "ces",
    "da": "dan",
    "nl": "nld",
    "no": "nor",
    "pl": "pol",
    "ro": "ron",
    "sv": "swe",
}
