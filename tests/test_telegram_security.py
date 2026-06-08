import pytest

pytest.importorskip("telegram_bot")

from unittest.mock import patch

from telegram_bot.config import TelegramAutoReply, TelegramPairingConfig, TelegramSettings
from telegram_bot.pairing import (
    approve_pairing,
    list_approved_user_ids,
    normalize_pairing_code,
    pairing_code_reply_text,
    reject_pairing,
    request_pairing,
    revoke_approved_user,
)
from telegram_bot.security import is_user_allowed, should_send_pairing_hint


def _settings(
    *,
    allowed: tuple[int, ...] = (),
    approved: tuple[int, ...] = (),
    dm_policy: str = "pairing",
) -> TelegramSettings:
    auto = TelegramAutoReply(
        enabled=True,
        mode="react",
        temperature=0.7,
        max_tokens=2048,
        provider=None,
        model=None,
        skip_rag=True,
        skip_context=True,
    )
    pairing = TelegramPairingConfig(code_ttl_sec=3600, hint_cooldown_sec=600)
    return TelegramSettings(
        enabled=True,
        bot_token="x",
        dm_policy=dm_policy,
        allowed_user_ids=allowed,
        approved_user_ids=approved,
        poll_timeout=30,
        pairing=pairing,
        auto_reply=auto,
    )


def test_unapproved_user_denied():
    assert not is_user_allowed(123, _settings())


def test_whitelisted_user_allowed_without_pairing():
    assert is_user_allowed(42, _settings(allowed=(42,)))


def test_approved_user_allowed():
    assert is_user_allowed(42, _settings(approved=(42,)))


def test_pairing_code_reply_contains_code():
    text = pairing_code_reply_text("PAIR-A7K2", 9_999_999_999.0)
    assert "PAIR-A7K2" in text


def test_pairing_hint_rate_limited():
    uid = 999001
    settings = _settings()
    assert should_send_pairing_hint(uid, settings) is True
    assert should_send_pairing_hint(uid, settings) is False


def test_allowlist_policy_denies_non_whitelist():
    assert not is_user_allowed(99, _settings(allowed=(42,), dm_policy="allowlist"))


def test_allowlist_policy_allows_whitelist():
    assert is_user_allowed(42, _settings(allowed=(42,), dm_policy="allowlist"))


def test_normalize_pairing_code():
    assert normalize_pairing_code("a7k2") == "PAIR-A7K2"


def test_pairing_request_and_approve(tmp_path):
    with patch("telegram_bot.pairing.config") as mock_cfg:
        mock_cfg.get.side_effect = lambda key, default=None: {
            "bridge": {"telegram": {"approved_user_ids": []}},
            "bridge.telegram": {"approved_user_ids": []},
            "bridge.telegram.pairing": {},
        }.get(key, default)
        mock_cfg.set = lambda *a, **k: None

        req = request_pairing(1001, username="alice", first_name="Ali")
        assert req is not None
        assert req.code.startswith("PAIR-")

        reused = request_pairing(1001)
        assert reused is not None
        assert reused.code == req.code
        assert reused.reused is True

        result = approve_pairing(req.code)
        assert result["user_id"] == 1001


def test_approve_invalid_code():
    with pytest.raises(LookupError):
        approve_pairing("PAIR-ZZZZ")


def test_reject_pairing():
    with patch("telegram_bot.pairing.config") as mock_cfg:
        mock_cfg.get.return_value = {"approved_user_ids": []}
        req = request_pairing(2002)
        assert req is not None
        out = reject_pairing(req.code)
        assert out["user_id"] == 2002


def test_revoke_persists(tmp_path, monkeypatch):
    from ly_next.core.config import Config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "bridge:\n  telegram:\n    approved_user_ids: [1, 2]\n",
        encoding="utf-8",
    )
    c = Config.__new__(Config)
    c.config_file = cfg_file
    c.default_config_file = cfg_file
    c.data_root = tmp_path
    c._config = {}
    c._cache = {}
    c._initialized = True
    c.load()

    monkeypatch.setattr("telegram_bot.pairing.config", c)
    assert revoke_approved_user(2) is True
    assert list_approved_user_ids() == [1]
