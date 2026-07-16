from __future__ import annotations

import sys
import unicodedata
from functools import cache

from hark.confirm_lexicon import NEGATE

APOSTROPHE_VARIANTS = (
    "\u2018",
    "\u02bc",
    "\u00b4",
    "\uff40",
    "\u1fef",
    "\u201b",
    "\u2032",
    "\u02b9",
)
NORMALIZATION_FORMS = (None, "NFC", "NFD", "NFKC", "NFKD")
UNSUPPORTED_IN_WORD_FRAGMENTS = (
    "\u00a8",
    "\u2033",
    "\uff3f",
    "\u0301",
    "\u02bb",
    "''",
    "\u2032\u2032",
)
COMPOSITE_CONTRACTION_SEPARATORS = (
    " \u2019",
    "\u2019 ",
    " _",
    "_ ",
    " \u02bb",
    "\u02bb ",
    " \u2033",
    "\u2033 ",
    "\u2019\u02bb",
)
ORDINARY_UNICODE_AFFIRMATIONS = (
    "yes I approve naïvely",
    "yes mañana",
    "yes résumé",
    "yes Ελληνικά",
)
BENIGN_PROSE_AFFIRMATIONS = (
    "yes candlelight",
    "yes canonical text",
    "yes Canada is great",
    "yes wonderful thought",
    "yes donate it",
    "YES CANDLELIGHT",
    "YES CANONICAL TEXT",
    "YES CANADA IS GREAT",
    "YES WONDERFUL THOUGHT",
    "YES DONATE IT",
)
WORD_BASE_BOUNDARY_CONTROLS = (
    "écan__t",
    "_can__t",
    "1can__t",
    "can__té",
    "can__t_",
    "can__t1",
)
TRANSPARENT_BOUNDARY_CHARACTERS = (
    "\u0301",  # Mn combining acute
    "\u0903",  # Mc Devanagari sign visarga
    "\u20dd",  # Me combining enclosing circle
    "\ufe0f",  # variation selector
    "\u200b",  # zero-width space
    "\u200d",  # zero-width joiner
    "\u2060",  # word joiner
)
COMPATIBILITY_EXPANSION_REPRODUCTIONS = (
    "\u2122",  # TRADE MARK SIGN -> TM
    "\u2100",  # ACCOUNT OF -> a/c
    "\u33c6",  # C OVER KG -> C/kg
    "\u2474",  # PARENTHESIZED DIGIT ONE -> (1)
)
CONTRACTION_PARTS = tuple(
    phrase.split("'", 1)
    for phrase in sorted(phrase for phrase in NEGATE if "'" in phrase)
)
EDGE_MATERIAL_REPRODUCTIONS = (
    "yes I can\u203ct\u0301 approve this",
    "yes I can\u203ct\ufe0f approve this",
    "yes I \u0301can\u203ct approve this",
    "yes I can\u200bt\u0301 approve this",
)
UNSUPPORTED_FULLWIDTH_SEPARATORS = (
    "__",
    "\u02bb",
    "\u2033",
    "\u2032\u2032",
    "\u2019\u02bb",
)


def fullwidth_ascii(text: str) -> str:
    return "".join(
        chr(ord(char) + 0xFEE0) if "!" <= char <= "~" else char for char in text
    )


FULLWIDTH_CONTRACTION_CASES = tuple(
    left_variant + separator + right_variant
    for left, right in CONTRACTION_PARTS
    for left_variant, right_variant in (
        (fullwidth_ascii(left), fullwidth_ascii(right)),
        (fullwidth_ascii(left), right),
        (left, fullwidth_ascii(right)),
    )
    for separator in UNSUPPORTED_FULLWIDTH_SEPARATORS
)
SUPPORTED_FULLWIDTH_CONTRACTION_CASES = tuple(
    left_variant + apostrophe + right_variant
    for left, right in CONTRACTION_PARTS
    for left_variant, right_variant in (
        (fullwidth_ascii(left), fullwidth_ascii(right)),
        (fullwidth_ascii(left), right),
        (left, fullwidth_ascii(right)),
    )
    for apostrophe in APOSTROPHE_VARIANTS
)
FULLWIDTH_WORD_BASE_BOUNDARY_CONTROLS = (
    "éｃａｎ__ｔ",
    "_ｃａｎ__ｔ",
    "ｃａｎ__ｔé",
    "ｃａｎ__ｔ_",
    "ｃａｎ__ｔ1",
)


@cache
def alphanumeric_compatibility_expansions() -> tuple[str, ...]:
    """All Unicode code points whose compatibility expansion contains a word base."""
    return tuple(
        char
        for codepoint in range(sys.maxunicode + 1)
        for char in (chr(codepoint),)
        if unicodedata.decomposition(char).startswith("<")
        and any(part.isalnum() for part in unicodedata.normalize("NFKD", char))
    )


@cache
def transparent_boundary_codepoints() -> tuple[str, ...]:
    return tuple(
        char
        for codepoint in range(sys.maxunicode + 1)
        for char in (chr(codepoint),)
        if unicodedata.category(char).startswith("M")
        or unicodedata.category(char) == "Cf"
    )


@cache
def word_base_category_representatives() -> tuple[str, ...]:
    categories = {"Lu", "Ll", "Lt", "Lm", "Lo", "Nd", "Nl", "No", "Pc"}
    representatives = {}
    for codepoint in range(sys.maxunicode + 1):
        char = chr(codepoint)
        category = unicodedata.category(char)
        if category in categories and category not in representatives:
            representatives[category] = char
    return tuple(representatives[category] for category in sorted(categories))
