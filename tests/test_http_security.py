from ly_next.core.http_security import parse_limit, path_matches_rule, rate_limit_bucket


def test_parse_limit_minute():
    assert parse_limit("120/minute") == (120, 60)


def test_parse_limit_invalid():
    assert parse_limit("nope") is None
    assert parse_limit("0/minute") is None


def test_path_matches_wildcard():
    assert path_matches_rule("/ly/static/app.js", "/ly/static/*")
    assert not path_matches_rule("/api/health", "/ly/static/*")


def test_rate_limit_bucket_login_post():
    class _Url:
        path = "/ly/login"

    class _Req:
        method = "POST"
        url = _Url()

    assert rate_limit_bucket(_Req()) == "login"


def test_rate_limit_bucket_api_auth_login():
    class _Url:
        path = "/api/auth/login"

    class _Req:
        method = "POST"
        url = _Url()

    assert rate_limit_bucket(_Req()) == "login"
