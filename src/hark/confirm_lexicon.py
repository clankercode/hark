"""Spoken confirmation / cancel lexicon for ask --confirm."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass

_PUNCTUATION = re.compile(r"[^\w\s']+", re.UNICODE)
_ADJOINING_PUNCTUATION_SEPARATOR = re.compile(r"^[^\w\s']+", re.UNICODE)
_CONFIRM_WHITESPACE = re.compile(r"\s+")
_PUNCTUATED_DEFER_CUES = ("but", "wait", "if", "unless")
_AFFIRMATIVE_IDIOMS = frozenset({"yes why not"})
_SUPPORTED_APOSTROPHE_SEPARATORS = frozenset(
    {
        "'",
        "`",  # grave accent / common STT substitution
        "\u00b4",  # acute accent
        "\u02b9",  # modifier letter prime
        "\u02bc",  # modifier letter apostrophe
        "\u1fef",  # Greek varia (canonically equivalent to grave)
        "\u2018",  # left single quotation mark
        "\u2019",  # right single quotation mark
        "\u201b",  # single high-reversed-9 quotation mark
        "\u2032",  # prime
        "\uff40",  # fullwidth grave accent
    }
)
_CONFIRM_APOSTROPHE_TRANSLATION = str.maketrans(
    {variant: "'" for variant in _SUPPORTED_APOSTROPHE_SEPARATORS}
)
_DECOMPOSED_SPACING_ACUTE = " \u0301"
_MAX_NORMALIZED_COMPATIBILITY_BRIDGE_CHARS = 7
_DISTINCTIVE_NORMALIZED_ALPHABETIC_BRIDGES = frozenset({"TM"})
# This limits one canonical ordering/composition segment, not transcript length.
# Human speech text should never need hundreds of marks on one starter; bounding
# the segment avoids the quadratic worst case in CPython's Unicode normalizer.
_MAX_NORMALIZATION_SEGMENT_CHARS = 256

AFFIRM = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "correct",
        "confirm",
        "confirmed",
        "send",
        "do it",
        "go ahead",
        "affirmative",
        "ok",
        "okay",
        "sure",
        "right",
    }
)

NEGATE = frozenset(
    {
        "no",
        "nope",
        "not",
        "cannot",
        "can't",
        "cant",
        "won't",
        "wont",
        "cancel",
        "abort",
        "stop",
        "don't",
        "dont",
        "do not",
        "deny",
        "denied",
        "reject",
        "rejected",
        "decline",
        "declined",
        "never mind",
        "nevermind",
        "negative",
        "wrong",
        "scratch",
    }
)

_CONTRACTION_PARTS = tuple(
    tuple(phrase.split("'", 1)) for phrase in NEGATE if phrase.count("'") == 1
)
_CONTRACTION_SEPARATOR_PATTERNS = tuple(
    re.compile(
        rf"{re.escape(left)}(?P<separator>[^a-z0-9]+){re.escape(right)}",
        re.IGNORECASE,
    )
    for left, right in _CONTRACTION_PARTS
)


@dataclass(frozen=True)
class _RawProjection:
    text: str
    raw_indices: tuple[int, ...]


@dataclass(frozen=True)
class _ContractionProvenance:
    has_unsupported_separator: bool
    canonical_input: str
    normalization_rejected: bool = False


def _direct_composition_result(first: str, second: str) -> str:
    """Resolve one bounded composition without normalizing attacker-sized text."""
    pair = first + second
    normalized = unicodedata.normalize("NFC", pair)
    return normalized if len(normalized) == 1 and normalized != pair else ""


def _advance_direct_composition_tail(tail: str, decomposition: str) -> str:
    for char in decomposition:
        if unicodedata.combining(char) != 0:
            tail = ""
        else:
            composite = _direct_composition_result(tail, char) if tail else ""
            tail = composite or char
    return tail


def _build_raw_projection(text: str) -> _RawProjection | None:
    """Return a raw-preserving NFKD view, or ``None`` for an oversized segment.

    Per-codepoint NFKD exposes compatibility expansions without allowing them to
    erase the raw character that produced them. The same pass bounds canonical
    ordering/composition segments before the classifier performs whole-input
    NFKC. All normalization calls here receive one or two input code points.
    """
    segment_size = 0
    composition_tail = ""
    output: list[str] = []
    raw_indices: list[int] = []
    for raw_index, char in enumerate(text):
        decomposition = unicodedata.normalize("NFKD", char)
        first = decomposition[0] if decomposition else ""
        continues_composition = bool(
            composition_tail
            and first
            and _direct_composition_result(composition_tail, first)
        )
        joins_segment = bool(segment_size) and (
            not first or unicodedata.combining(first) != 0 or continues_composition
        )
        if segment_size and not joins_segment:
            segment_size = 0
            composition_tail = ""
        segment_size += 1
        if segment_size > _MAX_NORMALIZATION_SEGMENT_CHARS:
            return None
        output.append(decomposition)
        raw_indices.extend([raw_index] * len(decomposition))
        composition_tail = _advance_direct_composition_tail(
            composition_tail, decomposition
        )
    return _RawProjection("".join(output), tuple(raw_indices))


def _canonical_input_with_replacements(
    text: str,
    replacements: dict[int, int],
) -> str:
    """Replace nonoverlapping raw spans with apostrophes in one linear pass."""
    if not replacements:
        return text
    parts: list[str] = []
    cursor = 0
    for start in range(len(text)):
        end = replacements.get(start)
        if end is None or start < cursor:
            continue
        parts.extend((text[cursor:start], "'"))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _is_confirmation_word_base(char: str) -> bool:
    category = unicodedata.category(char)
    return category[0] in {"L", "N"} or category == "Pc"


def _is_boundary_transparent(char: str) -> bool:
    category = unicodedata.category(char)
    return category[0] == "M" or category == "Cf"


def _neighboring_word_base(text: str, index: int, step: int) -> bool:
    while 0 <= index < len(text) and _is_boundary_transparent(text[index]):
        index += step
    return 0 <= index < len(text) and _is_confirmation_word_base(text[index])


def _is_complete_confirmation_span(text: str, start: int, end: int) -> bool:
    return not _neighboring_word_base(text, start - 1, -1) and not (
        _neighboring_word_base(text, end, 1)
    )


def _ascii_literal_at(text: str, start: int, literal: str) -> bool:
    end = start + len(literal)
    return end <= len(text) and text[start:end].lower() == literal


def _raw_material_for_projection_span(
    raw: str,
    projection: _RawProjection,
    start: int,
    end: int,
) -> tuple[int, int, str]:
    raw_start = projection.raw_indices[start]
    raw_end = projection.raw_indices[end - 1] + 1
    return raw_start, raw_end, raw[raw_start:raw_end]


def _is_compatibility_bridge_material(raw_material: str) -> bool:
    """Return whether an attached bridge has a compatibility-source shape.

    A raw compatibility code point is always attributable. Already-normalized
    material has lost that provenance, so only a compact, whitespace-free
    nonalphabetic shape or a named exact reproduction is fail-closed. This
    preserves forms such as ``TM``, ``a/c``, ``C/kg``, and ``(1)`` without
    treating ordinary words such as ``candlelight`` or ``donut`` as malformed.
    """
    if not raw_material or any(char.isspace() for char in raw_material):
        return False
    if len(raw_material) == 1 and unicodedata.decomposition(raw_material).startswith(
        "<"
    ):
        return True
    if len(raw_material) > _MAX_NORMALIZED_COMPATIBILITY_BRIDGE_CHARS:
        return False
    if raw_material.isalpha():
        return raw_material in _DISTINCTIVE_NORMALIZED_ALPHABETIC_BRIDGES
    return True


def _iter_compatibility_bridge_spans(
    raw: str, projection: _RawProjection
) -> Iterator[tuple[int, int]]:
    """Yield only attached bridges with a bounded compatibility-source shape."""
    text = projection.text
    for left, right in _CONTRACTION_PARTS:
        latest_left: tuple[int, int] | None = None
        for index in range(len(text)):
            left_end = index + len(left)
            if (
                _ascii_literal_at(text, index, left)
                and left_end < len(text)
                and not text[left_end].isspace()
                and not _neighboring_word_base(text, index - 1, -1)
            ):
                latest_left = (index, left_end)
            if latest_left is None or index <= latest_left[1]:
                continue
            right_end = index + len(right)
            if not (
                _ascii_literal_at(text, index, right)
                and not text[index - 1].isspace()
                and _is_complete_confirmation_span(text, latest_left[0], right_end)
            ):
                continue
            separator_span = (latest_left[1], index)
            first_source = projection.raw_indices[separator_span[0]]
            last_source = projection.raw_indices[separator_span[1] - 1]
            one_raw_source = first_source == last_source
            if not one_raw_source and (
                separator_span[1] - separator_span[0]
                > _MAX_NORMALIZED_COMPATIBILITY_BRIDGE_CHARS
                or last_source - first_source + 1
                > _MAX_NORMALIZED_COMPATIBILITY_BRIDGE_CHARS
            ):
                continue
            _, _, raw_material = _raw_material_for_projection_span(
                raw, projection, *separator_span
            )
            if _is_compatibility_bridge_material(raw_material):
                yield separator_span


def _analyze_contraction_provenance(text: str) -> _ContractionProvenance:
    """Validate raw material inside compatibility-expanded contractions.

    The raw-preserving NFKD projection exposes compatibility characters before
    they can erase a refusal skeleton. Candidate material must be one declared
    apostrophe equivalent or the exact SPACE+COMBINING ACUTE normalized form of
    U+00B4. Projection and scanning are O(input + projected output); an oversized
    canonical segment fails closed before whole-input normalization.
    """
    projection = _build_raw_projection(text)
    if projection is None:
        return _ContractionProvenance(False, text, normalization_rejected=True)
    has_unsupported_separator = False
    replacements: dict[int, int] = {}

    def validate_material(separator_start: int, separator_end: int) -> None:
        nonlocal has_unsupported_separator
        raw_start, raw_end, raw_material = _raw_material_for_projection_span(
            text, projection, separator_start, separator_end
        )
        if raw_material == _DECOMPOSED_SPACING_ACUTE:
            replacements[raw_start] = raw_end
            return
        if len(raw_material) == 1 and raw_material in _SUPPORTED_APOSTROPHE_SEPARATORS:
            return
        has_unsupported_separator = True

    for pattern in _CONTRACTION_SEPARATOR_PATTERNS:
        for match in pattern.finditer(projection.text):
            if _is_complete_confirmation_span(
                projection.text, match.start(), match.end()
            ):
                validate_material(*match.span("separator"))

    for separator_start, separator_end in _iter_compatibility_bridge_spans(
        text, projection
    ):
        validate_material(separator_start, separator_end)
    canonical_input = _canonical_input_with_replacements(text, replacements)
    return _ContractionProvenance(has_unsupported_separator, canonical_input)


def _normalize_confirmation_for_match(text: str) -> str:
    text = text.translate(_CONFIRM_APOSTROPHE_TRANSLATION)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CONFIRM_APOSTROPHE_TRANSLATION)
    return _CONFIRM_WHITESPACE.sub(" ", text.lower().strip())


def classify_confirm_reply(text: str) -> str:
    """Return 'yes' | 'no' | 'unclear'."""
    # Capture raw structure before compatibility normalization can erase it.
    raw = text or ""
    provenance = _analyze_contraction_provenance(raw)
    if provenance.normalization_rejected:
        return "unclear"
    t = _normalize_confirmation_for_match(provenance.canonical_input)
    # Preserve the parent classifier's fail-closed behavior for punctuated
    # deferrals/conditions. Broad unpunctuated language belongs to B148.
    for affirm in sorted(AFFIRM, key=len, reverse=True):
        if not t.startswith(affirm):
            continue
        tail = t[len(affirm) :]
        separator = _ADJOINING_PUNCTUATION_SEPARATOR.match(tail)
        if separator is None:
            continue
        remainder = tail[separator.end() :].strip()
        normalized_remainder = " ".join(_PUNCTUATION.sub(" ", remainder).split())
        if any(
            normalized_remainder == cue or normalized_remainder.startswith(cue + " ")
            for cue in _PUNCTUATED_DEFER_CUES
        ):
            return "unclear"
    # STT commonly preserves sentence-final punctuation. Confirmation is a
    # small spoken lexicon, so punctuation is non-semantic while apostrophes
    # remain meaningful for negatives such as ``don't``.
    t = " ".join(_PUNCTUATION.sub(" ", t).split())
    if not t:
        return "unclear"
    if t in AFFIRM:
        return "yes"
    if t in _AFFIRMATIVE_IDIOMS:
        return "yes"
    if t in NEGATE:
        return "no"
    # A bounded negative/refusal anywhere in a longer response wins over an
    # affirmative. This is deliberately conservative for permission and
    # destructive confirmations.
    padded = f" {t} "
    for n in sorted(NEGATE, key=len, reverse=True):
        if f" {n} " in padded:
            return "no"
    if provenance.has_unsupported_separator:
        return "unclear"
    for a in sorted(AFFIRM, key=len, reverse=True):
        if t == a or t.startswith(a + " ") or t.endswith(" " + a):
            return "yes"
    return "unclear"
