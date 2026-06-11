from ly_next.tools.image_prompt import (
    apply_negative_prompt,
    build_image_generation_input,
    extract_size_from_prompt,
    prepare_image_prompt,
)


def test_prepare_image_prompt_no_truncation(monkeypatch):
    monkeypatch.setattr(
        "ly_next.tools.image_prompt.config.get",
        lambda key, default=None: (
            2000
            if key == "tools.image.max_prompt_chars"
            else ("" if key == "tools.image.negative_prompt" else default)
        ),
    )
    text, truncated = prepare_image_prompt("short prompt")
    assert text == "short prompt"
    assert truncated is False


def test_prepare_image_prompt_truncates_long_text(monkeypatch):
    monkeypatch.setattr(
        "ly_next.tools.image_prompt.config.get",
        lambda key, default=None: (
            500
            if key == "tools.image.max_prompt_chars"
            else ("" if key == "tools.image.negative_prompt" else default)
        ),
    )
    long_text = "A scenic view. " * 80
    text, truncated = prepare_image_prompt(long_text)
    assert truncated is True
    assert len(text) <= 500


def test_extract_size_from_prompt_pixels():
    cleaned, size, source = extract_size_from_prompt(
        "Ultra-wide desktop wallpaper, 2560x1600, seaside sunset"
    )
    assert size == "2560x1600"
    assert source == "prompt"
    assert "2560x1600" not in cleaned


def test_extract_size_from_aspect_hint():
    _, size, source = extract_size_from_prompt("A calm 16:10 landscape scene")
    assert size == "1536x960"
    assert source == "hint"


def test_apply_negative_prompt_openai_style():
    pos, field = apply_negative_prompt("a cat", "watermark, text", mode="prompt")
    assert "Do not include" in pos
    assert field is None


def test_apply_negative_prompt_field_mode():
    pos, field = apply_negative_prompt("a cat", "blur", mode="field")
    assert pos == "a cat"
    assert field == "blur"


def test_build_image_generation_input_no_default_size(monkeypatch):
    monkeypatch.setattr(
        "ly_next.tools.image_prompt.config.get",
        lambda key, default=None: {
            "tools.image.max_prompt_chars": 2000,
            "tools.image.negative_prompt": "watermark",
            "tools.image.negative_prompt_mode": "prompt",
        }.get(key, default),
    )
    built = build_image_generation_input("sunset over ocean, ultra-wide")
    assert built.size == "1536x864"
    assert "Do not include" in built.prompt
    assert built.negative_prompt_field is None
