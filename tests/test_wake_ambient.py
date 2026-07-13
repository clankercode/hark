from hark.config import load_config
from hark.ambient import complete_after_wake
from hark.config import HarkConfig
from hark.speech import ListenResult
from hark.wake import (
    DEFAULT_ACTIVATION_PHRASES,
    TextProbeBackend,
    WakeHit,
    match_activation,
)


def test_activation_hey_hark():
    hit = match_activation("Hey Hark, open the PR checklist")
    assert hit is not None
    assert hit.phrase == "hey hark"
    assert "open the pr" in hit.remainder


def test_activation_hey_herald():
    hit = match_activation("hey herald")
    assert hit is not None
    assert hit.remainder == ""


def test_activation_anywhere_in_snippet():
    hit = match_activation("um yes hey hark ship it", anywhere=True)
    assert hit is not None
    assert hit.phrase == "hey hark"
    assert "ship" in hit.remainder


def test_no_false_wake_on_normal_speech():
    assert match_activation("please hark back to the earlier design") is None
    assert match_activation("the herald of spring arrived") is None
    # idiom "hark back …" is not a wake
    assert match_activation("hark back to the design") is None


def test_fuzzy_hey_hook_is_hark():
    # vosk often hears "hark" as "hook"
    hit = match_activation("hey hook", anywhere=True)
    assert hit is not None
    assert "hark" in hit.phrase


def test_fuzzy_hey_harold_is_herald():
    hit = match_activation("hey harold please", anywhere=True)
    assert hit is not None
    assert "herald" in hit.phrase


def test_hello_herald_wake():
    hit = match_activation("hello herald", anywhere=True)
    assert hit is not None
    assert "herald" in hit.phrase


def test_hello_hark_fuzzy():
    hit = match_activation("hello hook", anywhere=True)
    assert hit is not None
    assert "hark" in hit.phrase


def test_yo_and_sup_name_wake():
    hit = match_activation("yo herald", anywhere=True)
    assert hit is not None
    assert "herald" in hit.phrase
    hit = match_activation("yo hark ship it", anywhere=True)
    assert hit is not None
    assert "hark" in hit.phrase
    assert "ship" in hit.remainder
    hit = match_activation("yo harold please", anywhere=True)
    assert hit is not None
    assert "herald" in hit.phrase
    hit = match_activation("sup herald", anywhere=True)
    assert hit is not None
    assert hit.phrase == "sup herald"
    hit = match_activation("sup harold status", anywhere=True)
    assert hit is not None
    assert "herald" in hit.phrase
    assert "status" in hit.remainder
    hit = match_activation("sup hark", anywhere=True)
    assert hit is not None
    assert "hark" in hit.phrase


def test_bare_herald_and_harold_wake():
    for text in ("herald", "harold", "herold"):
        hit = match_activation(text, anywhere=True)
        assert hit is not None, f"expected bare wake for {text!r}"
        assert hit.phrase == "herald"
        assert hit.remainder == ""
        assert hit.backend == "text-bare"


def test_bare_herald_with_prompt_remainder():
    hit = match_activation("harold open the PR", anywhere=True)
    assert hit is not None
    assert hit.phrase == "herald"
    assert "open" in hit.remainder


def test_bare_hark_alone_wakes_but_idiom_does_not():
    hit = match_activation("hark", anywhere=True)
    assert hit is not None
    assert hit.phrase == "hark"
    assert match_activation("hark back to the design") is None
    # mid-sentence product name is not a wake
    assert match_activation("the herald of spring arrived", anywhere=True) is None


def test_filler_then_bare_product_wakes():
    hit = match_activation("um harold", anywhere=True)
    assert hit is not None
    assert hit.phrase == "herald"
    hit = match_activation("uh hark status", anywhere=True)
    assert hit is not None
    assert hit.phrase == "hark"
    assert "status" in hit.remainder


def test_text_probe_backend():
    be = TextProbeBackend()
    assert be.score_snippet(b"\x00\x01\x02\x03") is None
    hit = be.score_snippet(b"TXT:hey hark ship the feature")
    assert hit is not None
    assert hit.phrase == "hey hark"


def test_ambient_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[ambient]
enabled = true
engine = "text_probe"
activation_phrases = ["hey hark", "hey herald"]
snippet_s = 2.0
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("HARK_AMBIENT", raising=False)
    cfg = load_config(cfg_file)
    assert cfg.ambient.enabled is True
    assert cfg.ambient.engine == "text_probe"
    assert "hey herald" in cfg.ambient.activation_phrases


def test_default_activation_includes_herald():
    assert "hey hark" in DEFAULT_ACTIVATION_PHRASES
    assert "hey herald" in DEFAULT_ACTIVATION_PHRASES


def test_wake_remainder_is_discarded_and_cloud_listen_captures_prompt(monkeypatch):
    listened = ListenResult(
        text="cloud captured prompt",
        provider="xai",
        duration_ms=123,
        end_mode="radio",
    )
    calls = []

    def fake_listen(cfg, *, end_mode, **kwargs):
        calls.append((cfg, end_mode, kwargs))
        return listened

    monkeypatch.setattr("hark.ambient.run_listen", fake_listen)
    result = complete_after_wake(
        HarkConfig(),
        WakeHit(
            phrase="hey hark",
            remainder="locally heard but untrusted prompt",
            raw="hey hark locally heard but untrusted prompt",
            backend="vosk",
        ),
        announce=False,
    )

    assert calls and calls[0][1] == "silence"
    assert result.text == "cloud captured prompt"
    assert result.listen["provider"] == "xai"
