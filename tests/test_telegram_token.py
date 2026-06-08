import pytest

pytest.importorskip("telegram_bot")

from telegram_bot.token_check import (
    looks_like_telegram_bot_token,
    token_matches_api_key,
    validate_bot_token_format,
)


def test_valid_token_format():
    assert looks_like_telegram_bot_token("123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
    assert validate_bot_token_format("123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw") is None


def test_api_key_is_not_bot_token():
    key = "JMMABYVcDaNBCjRYA42lu4Y6JtkQF3WiZ72WcWYh9rg"
    assert not looks_like_telegram_bot_token(key)
    err = validate_bot_token_format(key)
    assert err is not None
    assert "BotFather" in err or "登录密钥" in err


def test_token_matches_api_key():
    key = "same-secret"
    assert token_matches_api_key(key, key)
    assert not token_matches_api_key("123:abc", key)
