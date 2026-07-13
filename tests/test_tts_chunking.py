"""B091: long TTS packs into sentence/word chunks — no mid-word hard cut."""

from __future__ import annotations

from types import SimpleNamespace

from hark.config import HarkConfig
from hark.speech import pack_tts_chunks, run_tts


def test_pack_under_limit_single_chunk():
    assert pack_tts_chunks("hello world", 500) == ["hello world"]


def test_pack_empty():
    assert pack_tts_chunks("  ", 500) == []
    assert pack_tts_chunks("", 0) == []


def test_pack_sentence_boundary_no_mid_word():
    # Dogfood text that previously hard-cut at "if Sh" of Sherpa
    text = (
        "Dry run of setup — no writes. One: health. Doctor is overall O K — "
        "Herdr default session up, x A I speech ready, ambient is set to Sherpa "
        "K W S but the Python package is missing, so wake may be on a fallback "
        "path until you run uv sync with the wake-sherpa extra. Two: sessions — "
        "you already have local default. Three: persona — feminine default is "
        "Iris with TTS eve; masculine is Mercury with leo. Four: wake backend — "
        "recommend Sherpa for product names, or Vosk if you want zero download. "
        "Five: if Sherpa, install the package and model. Six: say hey iris to "
        "confirm wake. Seven: write setup-complete flag — skipped on dry run. "
        "Want me to run real setup next, or just fix the Sherpa package warning?"
    )
    assert len(text) > 500
    chunks = pack_tts_chunks(text, 500)
    assert len(chunks) >= 2
    assert all(len(c) <= 500 for c in chunks)
    # First chunk must not end mid-token "Sh"
    assert not chunks[0].endswith("Sh")
    assert "Sherpa" in chunks[0] or "Sherpa" in chunks[1]
    # Rejoin preserves content words
    joined = " ".join(chunks)
    assert "wake-sherpa" in joined
    assert "setup-complete" in joined


def test_pack_word_boundary_long_sentence():
    words = " ".join(f"word{i}" for i in range(80))
    chunks = pack_tts_chunks(words, 40)
    assert len(chunks) > 1
    assert all(len(c) <= 40 for c in chunks)
    assert all(" " not in c or c == c.strip() for c in chunks)


def test_run_tts_plays_all_chunks(monkeypatch):
    plays: list[int] = []
    synth_calls: list[str] = []

    class FakeDuck:
        def __enter__(self):
            return SimpleNamespace(as_meta=lambda: {"media_ducked": False})

        def __exit__(self, *a):
            return False

    class FakeMute:
        def __enter__(self):
            return SimpleNamespace(applied=False)

        def __exit__(self, *a):
            return False

    def fake_lookup(*a, **k):
        return None

    def fake_resolve(*a, **k):
        class T:
            def synthesize(self, text, voice=None):
                synth_calls.append(text)
                return SimpleNamespace(
                    audio=b"AUD" + text[:8].encode(),
                    provider="xai",
                    content_type="audio/mpeg",
                    voice=voice or "eve",
                )

        return T()

    monkeypatch.setattr("hark.speech.lookup_cached_tts", fake_lookup)
    monkeypatch.setattr("hark.speech.store_cached_tts", lambda *a, **k: None)
    monkeypatch.setattr("hark.speech.resolve_tts", fake_resolve)
    monkeypatch.setattr(
        "hark.speech.play_wav_bytes",
        lambda audio, **k: plays.append(len(audio))
        or SimpleNamespace(duration_ms=100),
    )
    monkeypatch.setattr("hark.speech.duck_media", lambda *a, **k: FakeDuck())
    monkeypatch.setattr("hark.speech.mic_muted_during_tts", lambda **k: FakeMute())
    monkeypatch.setattr(
        "hark.speech.repair_tts_mute_after_play",
        lambda **k: {"repaired": False},
    )
    monkeypatch.setattr(
        "hark.conference.apply_conference_hold",
        lambda *a, **k: SimpleNamespace(
            skipped=False, as_meta=lambda: {"held": False}
        ),
    )

    long = ("Sentence one is here with more padding words. " * 15) + (
        "Final sentence ends here."
    )
    assert len(long) > 500
    cfg = HarkConfig()
    cfg.tts.max_chars = 500
    cfg.audio.hold_during_conference = False
    out = run_tts(cfg, long, play=True, conference_policy="force", use_cache=False)
    assert out["ok"] is True
    assert out["truncated"] is False
    assert out["chunked"] is True
    assert out["chunks"] >= 2
    assert out["chars"] == len(long.strip())
    assert len(synth_calls) == out["chunks"]
    assert len(plays) == out["chunks"]
    assert sum(len(s) for s in synth_calls) >= len(long) - 5
