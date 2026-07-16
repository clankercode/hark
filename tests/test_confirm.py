import unicodedata

import pytest

import hark.confirm_lexicon as confirm_lexicon
from confirm_unicode_cases import (
    APOSTROPHE_VARIANTS,
    BENIGN_PROSE_AFFIRMATIONS,
    COMPATIBILITY_EXPANSION_REPRODUCTIONS,
    COMPOSITE_CONTRACTION_SEPARATORS,
    CONTRACTION_PARTS,
    EDGE_MATERIAL_REPRODUCTIONS,
    FULLWIDTH_CONTRACTION_CASES,
    FULLWIDTH_WORD_BASE_BOUNDARY_CONTROLS,
    NORMALIZATION_FORMS,
    ORDINARY_UNICODE_AFFIRMATIONS,
    SUPPORTED_FULLWIDTH_CONTRACTION_CASES,
    TRANSPARENT_BOUNDARY_CHARACTERS,
    UNSUPPORTED_IN_WORD_FRAGMENTS,
    WORD_BASE_BOUNDARY_CONTROLS,
    alphanumeric_compatibility_expansions,
    transparent_boundary_codepoints,
    word_base_category_representatives,
)
from hark.confirm_lexicon import classify_confirm_reply


def test_affirm():
    assert classify_confirm_reply("yes") == "yes"
    assert classify_confirm_reply("OK send it") == "yes"


@pytest.mark.parametrize(
    "reply",
    ["Yes.", " YES! ", "\tYeS.\n", "Okay.", "GO AHEAD!"],
)
def test_affirm_ignores_terminal_punctuation_casing_and_whitespace(reply):
    assert classify_confirm_reply(reply) == "yes"


def test_negate():
    assert classify_confirm_reply("cancel") == "no"
    assert classify_confirm_reply("nope") == "no"


@pytest.mark.parametrize(
    "reply",
    [
        "No, yes.",
        "Not okay.",
        "Yes — cancel.",
        "Yes, I cannot approve this.",
        "Yes, I can't approve this.",
        "Yes, I won't approve this.",
        "Yes, reject it.",
    ],
)
def test_negative_phrase_wins_over_affirmative(reply):
    assert classify_confirm_reply(reply) == "no"


@pytest.mark.parametrize("normalization", NORMALIZATION_FORMS)
@pytest.mark.parametrize("apostrophe", APOSTROPHE_VARIANTS)
def test_negative_contractions_accept_normalization_closed_apostrophe_family(
    apostrophe, normalization
):
    reply = f"yes I can{apostrophe}t approve this"
    if normalization is not None:
        reply = unicodedata.normalize(normalization, reply)
    assert classify_confirm_reply(reply) == "no"


@pytest.mark.parametrize(
    "reply",
    [
        "yes, I scant approve",
        *(f"yes, can{apostrophe}tastic" for apostrophe in APOSTROPHE_VARIANTS),
    ],
)
def test_negative_contractions_preserve_whole_token_boundaries(reply):
    assert classify_confirm_reply(reply) == "yes"


def test_unknown_in_word_punctuation_cannot_become_approval():
    assert classify_confirm_reply("yes I can\u055at approve this") == "unclear"


@pytest.mark.parametrize("normalization", NORMALIZATION_FORMS)
@pytest.mark.parametrize("fragment", UNSUPPORTED_IN_WORD_FRAGMENTS)
def test_lossy_or_repeated_in_word_material_cannot_become_approval(
    fragment, normalization
):
    reply = f"yes I can{fragment}t approve this"
    if normalization is not None:
        reply = unicodedata.normalize(normalization, reply)
    assert classify_confirm_reply(reply) == "unclear"


@pytest.mark.parametrize("separator", COMPOSITE_CONTRACTION_SEPARATORS)
def test_composite_contraction_separator_cannot_become_approval(separator):
    assert classify_confirm_reply(f"yes I can{separator}t approve this") == "unclear"


@pytest.mark.parametrize("reply", ORDINARY_UNICODE_AFFIRMATIONS)
def test_ordinary_unicode_words_do_not_block_affirmation(reply):
    assert classify_confirm_reply(reply) == "yes"


@pytest.mark.parametrize("reply", BENIGN_PROSE_AFFIRMATIONS)
def test_contraction_prefixes_in_benign_prose_do_not_block_affirmation(reply):
    assert classify_confirm_reply(reply) == "yes"


@pytest.mark.parametrize("token", WORD_BASE_BOUNDARY_CONTROLS)
def test_malformed_contraction_inside_unicode_token_does_not_block_affirmation(token):
    assert classify_confirm_reply(f"yes {token}") == "yes"


def test_standalone_malformed_contraction_still_blocks_affirmation():
    assert classify_confirm_reply("yes can__t") == "unclear"


@pytest.mark.parametrize("token", FULLWIDTH_CONTRACTION_CASES)
def test_fullwidth_or_mixed_contraction_skeleton_preserves_separator_provenance(token):
    assert classify_confirm_reply(f"yes {token}") == "unclear"


@pytest.mark.parametrize("token", SUPPORTED_FULLWIDTH_CONTRACTION_CASES)
def test_fullwidth_or_mixed_contraction_accepts_supported_apostrophe(token):
    assert classify_confirm_reply(f"yes {token}") == "no"


@pytest.mark.parametrize("token", FULLWIDTH_WORD_BASE_BOUNDARY_CONTROLS)
def test_fullwidth_malformed_contraction_inside_unicode_token_does_not_block(token):
    assert classify_confirm_reply(f"yes {token}") == "yes"


@pytest.mark.parametrize("character", COMPATIBILITY_EXPANSION_REPRODUCTIONS)
@pytest.mark.parametrize("normalization", NORMALIZATION_FORMS)
def test_alphanumeric_compatibility_expansion_cannot_erase_refusal(
    character, normalization
):
    material = (
        character
        if normalization is None
        else unicodedata.normalize(normalization, character)
    )

    assert classify_confirm_reply(f"yes I can{material}t approve this") != "yes"


def test_all_attributable_alphanumeric_compatibility_expansions_fail_closed():
    failures = []
    expansions = alphanumeric_compatibility_expansions()
    audited = 0

    for character in expansions:
        for normalization in NORMALIZATION_FORMS:
            material = (
                character
                if normalization is None
                else unicodedata.normalize(normalization, character)
            )
            provenance_preserved = normalization in {None, "NFC", "NFD"}
            distinctive_normalized_shape = (
                not any(char.isspace() for char in material)
                and len(material) <= 7
                and (not material.isalpha() or material == "TM")
            )
            if not provenance_preserved and not distinctive_normalized_shape:
                continue
            for left, right in CONTRACTION_PARTS:
                audited += 1
                reply = f"yes I {left}{material}{right} approve this"
                if classify_confirm_reply(reply) == "yes":
                    failures.append(
                        (f"U+{ord(character):04X}", normalization, left, right)
                    )
                    if len(failures) == 20:
                        break
            if len(failures) == 20:
                break
        if len(failures) == 20:
            break

    assert len(expansions) >= 3000
    assert audited >= 30_000
    assert failures == []


@pytest.mark.parametrize("reply", EDGE_MATERIAL_REPRODUCTIONS)
@pytest.mark.parametrize("normalization", NORMALIZATION_FORMS)
def test_transparent_edge_material_cannot_hide_malformed_contraction(
    reply, normalization
):
    if normalization is not None:
        reply = unicodedata.normalize(normalization, reply)
    assert classify_confirm_reply(reply) == "unclear"


@pytest.mark.parametrize("edge", TRANSPARENT_BOUNDARY_CHARACTERS)
def test_extend_format_and_variation_boundaries_remain_fail_closed(edge):
    assert classify_confirm_reply(f"yes I {edge}can__t approve") == "unclear"
    assert classify_confirm_reply(f"yes I can__t{edge} approve") == "unclear"


def test_all_unicode_extend_and_format_edges_remain_fail_closed():
    failures = []
    edges = transparent_boundary_codepoints()

    for edge in edges:
        replies = (f"yes I {edge}can__t", f"yes I can__t{edge}")
        if any(classify_confirm_reply(reply) == "yes" for reply in replies):
            failures.append(f"U+{ord(edge):04X}")
            if len(failures) == 20:
                break

    assert len(edges) >= 2000
    assert failures == []


def test_every_word_base_category_still_blocks_embedded_candidate():
    for base in word_base_category_representatives():
        assert classify_confirm_reply(f"yes {base}can__t") == "yes"
        assert classify_confirm_reply(f"yes can__t{base}") == "yes"


def _alternating_out_of_order_marks(length):
    return ("\u0315\u0300" * ((length + 1) // 2))[:length]


@pytest.mark.parametrize(
    "prefix",
    [
        "",  # leading combining marks
        "a",  # starter plus combining marks
        "\u1100\u1161\u11a8",  # algorithmic Hangul L/V/T composition
        "\u09c7\u09be",  # Bengali CCC-zero canonical composition
        "\u00b4",  # compatibility SPACE + COMBINING ACUTE expansion
    ],
)
def test_normalization_segment_guard_accepts_limit_and_rejects_next_char(
    monkeypatch, prefix
):
    limit = confirm_lexicon._MAX_NORMALIZATION_SEGMENT_CHARS
    at_limit = prefix + _alternating_out_of_order_marks(limit - len(prefix))
    over_limit = at_limit + "\u0315"
    real_normalize = confirm_lexicon.unicodedata.normalize
    calls = []

    def counted_normalize(form, text):
        calls.append((form, len(text)))
        return real_normalize(form, text)

    monkeypatch.setattr(confirm_lexicon.unicodedata, "normalize", counted_normalize)

    assert classify_confirm_reply(at_limit) == "unclear"
    assert any(form == "NFKC" and length == len(at_limit) for form, length in calls)

    calls.clear()
    assert classify_confirm_reply(over_limit) == "unclear"
    assert all(length <= 2 for _, length in calls)


def test_long_pathological_combining_segment_fails_before_whole_normalization(
    monkeypatch,
):
    real_normalize = confirm_lexicon.unicodedata.normalize
    normalized_lengths = []

    def counted_normalize(form, text):
        normalized_lengths.append(len(text))
        return real_normalize(form, text)

    monkeypatch.setattr(confirm_lexicon.unicodedata, "normalize", counted_normalize)
    raw = _alternating_out_of_order_marks(8000)

    assert classify_confirm_reply(raw) == "unclear"
    assert len(normalized_lengths) == (
        confirm_lexicon._MAX_NORMALIZATION_SEGMENT_CHARS + 1
    )
    assert max(normalized_lengths) == 1


def test_segment_guard_does_not_cap_ordinary_text_or_decomposed_spacing_acute():
    long_ordinary_reply = "yes " + "naïve Ελληνικά " * 600

    assert classify_confirm_reply(long_ordinary_reply) == "yes"
    assert classify_confirm_reply("yes I can \u0301t approve this") == "no"


def test_classifier_reconstructs_many_decomposed_apostrophes_in_linear_work(
    monkeypatch,
):
    real_normalize = confirm_lexicon.unicodedata.normalize
    real_rebuild = confirm_lexicon._canonical_input_with_replacements
    normalization_work = 0
    rebuild_samples = []

    def counted_normalize(form, text):
        nonlocal normalization_work
        normalization_work += len(text)
        return real_normalize(form, text)

    def counted_rebuild(text, replacements):
        class CountingReplacements(dict):
            get_calls = 0

            def get(self, key, default=None):
                self.get_calls += 1
                return super().get(key, default)

        counted = CountingReplacements(replacements)
        result = real_rebuild(text, counted)
        rebuild_samples.append(
            (len(text), len(counted), counted.get_calls, len(result))
        )
        return result

    monkeypatch.setattr(confirm_lexicon.unicodedata, "normalize", counted_normalize)
    monkeypatch.setattr(
        confirm_lexicon,
        "_canonical_input_with_replacements",
        counted_rebuild,
    )

    def measure(repetitions):
        nonlocal normalization_work
        normalization_work = 0
        rebuild_samples.clear()
        raw = "can \u0301t " * repetitions

        assert classify_confirm_reply(raw) == "no"
        assert rebuild_samples == [
            (len(raw), repetitions, len(raw), len(raw) - repetitions)
        ]
        return normalization_work

    small_work = measure(1024)
    large_work = measure(2048)

    assert large_work <= 2 * small_work + 16


@pytest.mark.parametrize(
    "reply",
    [
        "yes I cant approve this",
        "yes I wont approve this",
        "yes I dont approve this",
    ],
)
def test_apostropheless_negative_contractions_win_over_affirmative(reply):
    assert classify_confirm_reply(reply) == "no"


@pytest.mark.parametrize(
    "reply",
    [
        "yes the cantilever design is approved",
        "yes I want wonton soup",
    ],
)
def test_apostropheless_negative_contractions_match_whole_words(reply):
    assert classify_confirm_reply(reply) == "yes"


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, but wait.",
        "Okay, wait a second.",
        "Yes, if the tests pass.",
        "Yes, wait.",
        "Yes, but.",
        "Okay, if.",
        "Yes, unless.",
        "Yes; wait.",
        "Yes—wait.",
        "Yes. Wait.",
        "Yes: wait.",
        "Sure; if tests pass.",
        "Yes? If tests pass.",
        "Yes… unless reviewed.",
        "Okay… wait.",
        "Go ahead—unless reviewed.",
        "Yes—but go ahead.",
    ],
)
def test_punctuated_defer_remains_unclear(reply):
    """B142 parent behavior: punctuation must not turn deferral into approval."""
    assert classify_confirm_reply(reply) == "unclear"


def test_yes_why_not_is_affirmative_idiom():
    assert classify_confirm_reply("yes why not") == "yes"
    assert classify_confirm_reply("Yes, why not?") == "yes"


def test_unclear():
    assert classify_confirm_reply("maybe later purple") == "unclear"
