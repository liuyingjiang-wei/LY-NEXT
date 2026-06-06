from ly_next.bridge.onebot11.paths import DEFAULT_ONEBOT11_WS_PATHS, is_onebot11_ws_path


def test_is_onebot11_ws_path():
    assert is_onebot11_ws_path("/onebot/v11/ws")
    assert is_onebot11_ws_path("/OneBotv11")
    assert not is_onebot11_ws_path("/api/ws/OneBot11")
    assert not is_onebot11_ws_path("/api/ws/stdin")


def test_default_paths():
    assert "/onebot/v11/ws" in DEFAULT_ONEBOT11_WS_PATHS
    assert "/api/ws/OneBot11" not in DEFAULT_ONEBOT11_WS_PATHS
