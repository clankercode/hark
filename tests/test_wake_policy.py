"""WakePolicy: name-based vs full-phrase modes + dynamic learning."""

from __future__ import annotations

from hark.config import resolve_wake_policy
from hark.wake import (
    NearMiss,
    WakePolicy,
    match_activation,
    plausible_near_miss,
    suggest_learn_from_near_miss,
)
from hark.wake_learn import (
    is_learnable_name_alias,
    learn_name_alias,
    learn_phrase_alias,
    load_learned,
)


def test_names_mode_defaults_match_hey_and_bare():
    pol = WakePolicy(mode="names", names=["hark", "herald"])
    assert match_activation("hey hark", policy=pol) is not None
    assert match_activation("sup herald", policy=pol, anywhere=True) is not None
    assert match_activation("harold", policy=pol, anywhere=True) is not None
    assert match_activation("yo hark ship it", policy=pol, anywhere=True).remainder  # type: ignore[union-attr]


def test_names_mode_custom_name():
    pol = WakePolicy(mode="names", names=["alice"])
    assert match_activation("hey alice", policy=pol, anywhere=True) is not None
    assert match_activation("alice", policy=pol, anywhere=True) is not None
    assert match_activation("herald", policy=pol, anywhere=True) is None
    assert match_activation("hey hark", policy=pol, anywhere=True) is None


def test_phrases_mode_ignores_names():
    pol = WakePolicy(mode="phrases", names=[], phrases=["start prompt"])
    assert match_activation("start prompt go", policy=pol, anywhere=True) is not None
    assert match_activation("harold", policy=pol, anywhere=True) is None
    assert match_activation("hey hark", policy=pol, anywhere=True) is None
    assert match_activation("yo herald", policy=pol, anywhere=True) is None


def test_resolve_wake_mode_names_and_phrases():
    n = resolve_wake_policy({"names": ["hark", "alice"]}, load_learned_state=False)
    assert n.normalized_mode() == "names"
    assert "alice" in n.canonical_names()
    p = resolve_wake_policy(
        {"trigger_phrases": ["start prompt"]}, load_learned_state=False
    )
    assert p.normalized_mode() == "phrases"
    assert p.phrases == ["start prompt"]


def test_learn_name_alias_then_match(tmp_path, monkeypatch):
    path = tmp_path / "wake_learned.json"
    monkeypatch.setenv("HARK_WAKE_LEARNED", str(path))
    pol = WakePolicy(mode="names", names=["hark", "herald"], learn=True)
    assert match_activation("hey hoc", policy=pol, anywhere=True) is None
    state, changed = learn_name_alias("hoc", "hark", path=path)
    assert changed
    pol2 = pol.merge_learned(name_aliases=state.name_aliases)
    hit = match_activation("hey hoc", policy=pol2, anywhere=True)
    assert hit is not None
    assert "hark" in hit.phrase
    # Persist + reload
    reloaded = load_learned(path)
    assert reloaded.name_aliases.get("hoc") == "hark"


def test_learn_phrase_alias_then_match(tmp_path, monkeypatch):
    path = tmp_path / "wake_learned.json"
    monkeypatch.setenv("HARK_WAKE_LEARNED", str(path))
    pol = WakePolicy(mode="phrases", phrases=["start prompt"], learn=True)
    assert match_activation("start promt", policy=pol, anywhere=True) is None
    state, changed = learn_phrase_alias("start promt", path=path)
    assert changed
    pol2 = pol.merge_learned(phrase_aliases=state.phrase_aliases)
    hit = match_activation("start promt ship", policy=pol2, anywhere=True)
    assert hit is not None
    assert "start promt" in hit.phrase


def test_suggest_learn_from_near_miss_names():
    pol = WakePolicy(mode="names", names=["hark", "herald"], learn=True)
    miss = NearMiss(
        text="hey hoc", best_phrase="hey hark", score=0.6, reason="prefix_product_near"
    )
    sug = suggest_learn_from_near_miss(miss, pol)
    assert sug is not None
    kind, value, canon = sug
    assert kind == "name"
    assert value == "hoc"
    assert canon == "hark"


def test_suggest_learn_rejects_tts_bleed_is_to_iris():
    """TTS sample “Hello. This is Eve…” must not teach is→iris (B077)."""
    pol = WakePolicy(
        mode="names", names=["iris", "mercury", "hark", "herald"], learn=True
    )
    for text in (
        "hello this is eve",
        "this is eve",
        "hey is",
        "is",
        "hello this is english calm",
    ):
        miss = NearMiss(
            text=text,
            best_phrase="hey iris",
            score=0.6,
            reason="prefix_product_near",
        )
        assert suggest_learn_from_near_miss(miss, pol) is None, text


def test_suggest_learn_rejects_short_and_stopword_aliases():
    pol = WakePolicy(
        mode="names", names=["iris", "mercury", "hark", "herald"], learn=True
    )
    # len < 3 or function words even when edit-similar
    for text, reason in (
        ("hey ha", "prefix_product_near"),  # len 2
        ("hey he", "prefix_product_near"),  # stop + len 2
        ("her", "short_product_near"),  # pronoun ~ herald
        ("his", "short_product_near"),
        ("the", "short_product_near"),
        ("hey her", "prefix_product_near"),
    ):
        miss = NearMiss(
            text=text, best_phrase="hey herald", score=0.6, reason=reason
        )
        assert suggest_learn_from_near_miss(miss, pol) is None, text


def test_suggest_learn_allows_real_mishears():
    pol = WakePolicy(
        mode="names", names=["iris", "mercury", "hark", "herald"], learn=True
    )
    cases = [
        ("eyris", "iris"),
        ("irys", "iris"),
        ("mercery", "mercury"),
        ("hey eyris", "iris"),
        ("hey hoc", "hark"),
    ]
    for text, want_canon in cases:
        miss = NearMiss(
            text=text,
            best_phrase=f"hey {want_canon}",
            score=0.6,
            reason="prefix_product_near",
        )
        sug = suggest_learn_from_near_miss(miss, pol)
        assert sug is not None, text
        kind, value, canon = sug
        assert kind == "name"
        assert canon == want_canon
        assert value not in ("is", "he", "her", "the")
        assert len(value) >= 3


def test_is_learnable_name_alias_denylist():
    assert is_learnable_name_alias("hoc")
    assert is_learnable_name_alias("eyris")
    assert is_learnable_name_alias("irys")
    assert is_learnable_name_alias("mercery")
    assert not is_learnable_name_alias("is")
    assert not is_learnable_name_alias("he")
    assert not is_learnable_name_alias("her")
    assert not is_learnable_name_alias("ha")  # min len 3
    assert not is_learnable_name_alias("a")
    assert not is_learnable_name_alias("the")
    assert not is_learnable_name_alias("this")
    assert not is_learnable_name_alias("eve")  # TTS voice bleed
    assert not is_learnable_name_alias("")
    assert not is_learnable_name_alias("  ")
    assert not is_learnable_name_alias("ab")  # too short
    assert not is_learnable_name_alias("x" * 13)  # too long


def test_learn_name_alias_refuses_stopwords(tmp_path, monkeypatch):
    path = tmp_path / "wake_learned.json"
    monkeypatch.setenv("HARK_WAKE_LEARNED", str(path))
    state, changed = learn_name_alias("is", "iris", path=path)
    assert not changed
    assert "is" not in state.name_aliases
    state, changed = learn_name_alias("eyris", "iris", path=path)
    assert changed
    assert state.name_aliases.get("eyris") == "iris"


def test_load_learned_strips_bad_aliases(tmp_path, monkeypatch):
    path = tmp_path / "wake_learned.json"
    monkeypatch.setenv("HARK_WAKE_LEARNED", str(path))
    path.write_text(
        '{"version":1,"name_aliases":{"is":"iris","hoc":"hark","her":"herald"},'
        '"phrase_aliases":[]}\n',
        encoding="utf-8",
    )
    reloaded = load_learned(path)
    assert "is" not in reloaded.name_aliases
    assert "her" not in reloaded.name_aliases
    assert reloaded.name_aliases.get("hoc") == "hark"


def test_suggest_learn_from_near_miss_phrases():
    pol = WakePolicy(mode="phrases", phrases=["start prompt"], learn=True)
    miss = NearMiss(
        text="start promt",
        best_phrase="start prompt",
        score=0.8,
        reason="phrase_similarity",
    )
    sug = suggest_learn_from_near_miss(miss, pol)
    assert sug is not None
    assert sug[0] == "phrase"
    assert sug[1] == "start promt"


def test_near_miss_then_learned_not_near_miss(tmp_path, monkeypatch):
    path = tmp_path / "wake_learned.json"
    monkeypatch.setenv("HARK_WAKE_LEARNED", str(path))
    pol = WakePolicy(mode="names", names=["hark"], learn=True)
    assert plausible_near_miss("hey hoc", policy=pol) is not None
    state, _ = learn_name_alias("hoc", "hark", path=path)
    pol2 = pol.merge_learned(name_aliases=state.name_aliases)
    assert match_activation("hey hoc", policy=pol2, anywhere=True) is not None
    assert plausible_near_miss("hey hoc", policy=pol2) is None
