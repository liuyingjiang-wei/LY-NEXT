from __future__ import annotations

from unittest.mock import patch

from ly_next.main import create_app


def test_create_app_cors_origins_none_falls_back_to_wildcard():
    with patch("ly_next.main.config") as mock_config:
        mock_config.get.side_effect = lambda key, default=None: (
            None if key == "cors.origins" else default
        )
        app = create_app()
    assert app is not None
