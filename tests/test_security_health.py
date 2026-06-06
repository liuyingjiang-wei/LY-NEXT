from ly_next.core.security_health import gather_security_health


def test_security_health_returns_checks():
    data = gather_security_health()
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert len(data["checks"]) >= 5
    assert "all_ok" in data
    assert "suggestions" in data


def test_security_health_auth_enabled_by_default():
    data = gather_security_health()
    auth = next(c for c in data["checks"] if c["id"] == "auth_enabled")
    assert auth["ok"] is True
