from __future__ import annotations

from unittest.mock import patch

from ly_next.main import create_app


def test_create_app_cors_origins_none_falls_back_to_localhost():
    with patch("ly_next.main.config") as mock_config:
        mock_config.get.side_effect = lambda key, default=None: (
            None if key == "cors.origins" else default
        )
        app = create_app()
    assert app is not None
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_origins"] == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
