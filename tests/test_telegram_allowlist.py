import pytest

pytest.importorskip("telegram_bot")

from telegram_bot.allowlist import (
    normalize_allow_from_entry,
    parse_allow_from,
    parse_user_ids,
    validate_user_id_format,
    verify_allowlist_user,
)


def test_parse_user_ids():
    assert parse_user_ids([1, "2", 0, -1, "x"]) == [1, 2]


def test_parse_telegram_prefixed_id():
    ids, rejected = parse_allow_from(["telegram:6537629878", "tg:42"])
    assert ids == [42, 6537629878]
    assert not rejected


def test_parse_thread_style_id():
    uid, err = normalize_allow_from_entry("telegram:chat:6537629878:user:6537629878")
    assert err is None
    assert uid == 6537629878


def test_reject_username():
    uid, err = normalize_allow_from_entry("@woshihutaodegou")
    assert uid is None
    assert "@用户名" in (err or "")


def test_validate_user_id_format():
    assert validate_user_id_format(6537629878) is None
    assert validate_user_id_format(0) is not None


@pytest.mark.asyncio
async def test_verify_allowlist_without_token():
    out = await verify_allowlist_user("", 12345)
    assert out["ok"] is True
    assert out["reachable"] is None


@pytest.mark.asyncio
async def test_verify_allowlist_invalid_id():
    out = await verify_allowlist_user("fake-token", -1)
    assert out["ok"] is False
