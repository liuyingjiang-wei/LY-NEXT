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


def test_security_health_includes_p0_checks():
    data = gather_security_health()
    ids = {c["id"] for c in data["checks"]}
    for expected in (
        "api_security_profile",
        "plugins_security_profile",
        "tools_security_profile",
        "host_tools",
        "web_scrape_builtin",
        "web_scrape_denied",
        "docs_whitelist",
        "security_headers",
        "audit_log",
        "agent_content_policy",
    ):
        assert expected in ids
