"""工作台未登录跳转与登录后 next 参数校验。"""

from ly_next.main import _login_redirect_url, _safe_ly_next_path


def test_safe_ly_next_path_rejects_external():
    assert _safe_ly_next_path("//evil.com") == "/ly/"
    assert _safe_ly_next_path("https://x") == "/ly/"
    assert _safe_ly_next_path("/ly\\evil") == "/ly/"
    assert _safe_ly_next_path("/ly/foo@bar") == "/ly/"


def test_safe_ly_next_path_allows_workbench():
    assert _safe_ly_next_path("/ly/") == "/ly/"
    assert _safe_ly_next_path("/ly/app") == "/ly/app"


def test_safe_ly_next_path_blocks_login_and_static():
    assert _safe_ly_next_path("/ly/login") == "/ly/"
    assert _safe_ly_next_path("/ly/static/foo.js") == "/ly/"


class _FakeURL:
    def __init__(self, path: str, query: str = ""):
        self.path = path
        self.query = query


class _FakeRequest:
    def __init__(self, path: str, query: str = ""):
        self.url = _FakeURL(path, query)


def test_login_redirect_url_includes_next():
    url = _login_redirect_url(_FakeRequest("/ly/", "tab=chat"))
    assert url == "/ly/login?next=/ly/?tab=chat"
