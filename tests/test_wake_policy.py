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
