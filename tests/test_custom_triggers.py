from hark.config import load_config, resolve_activation_phrases
from hark.wake import DEFAULT_ACTIVATION_PHRASES, match_activation


def test_start_prompt_as_custom_trigger():
    hit = match_activation(
        "start prompt please open the PR",
        ["start prompt", "hey hark"],
        anywhere=True,
    )
    assert hit is not None
    assert hit.phrase == "start prompt"
    assert "open the pr" in hit.remainder


def test_resolve_extra_appends_defaults():
    phrases = resolve_activation_phrases(
        {"extra_trigger_phrases": ["start prompt", "begin dictation"]}
    )
    assert "start prompt" in phrases
    assert "begin dictation" in phrases
    assert "hey hark" in phrases
    # defaults still present
    for p in DEFAULT_ACTIVATION_PHRASES:
        assert p in phrases


def test_custom_only_phrases_skip_bare_product_fuzzy():
    """Replacing defaults with non-product phrases keeps bare herald exclusive."""
    phrases = resolve_activation_phrases({"trigger_phrases": ["start prompt"]})
    assert match_activation("harold", phrases, anywhere=True) is None
    assert match_activation("yo hark", phrases, anywhere=True) is None
    assert match_activation("start prompt ship it", phrases, anywhere=True) is not None


def test_resolve_trigger_phrases_replaces_defaults():
    phrases = resolve_activation_phrases({"trigger_phrases": ["start prompt"]})
    assert phrases == ["start prompt"]
    assert "hey hark" not in phrases


def test_resolve_activation_and_extra_merge():
    phrases = resolve_activation_phrases(
        {
            "activation_phrases": ["hey hark"],
            "extra_activation_phrases": ["start prompt"],
        }
    )
    # Names mode (hark present): display list includes name greating samples + extras
    assert "hey hark" in phrases
    assert "start prompt" in phrases


def test_load_config_extra_trigger_phrases(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[ambient]
enabled = true
extra_trigger_phrases = ["start prompt"]
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert "start prompt" in cfg.ambient.activation_phrases
    assert "hey hark" in cfg.ambient.activation_phrases
    hit = match_activation(
        "Start Prompt ship the feature",
        cfg.ambient.activation_phrases,
        anywhere=True,
    )
    assert hit is not None
    assert hit.phrase == "start prompt"
