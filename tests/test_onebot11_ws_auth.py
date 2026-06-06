import json

from fastapi.testclient import TestClient

from ly_next.main import create_app


def test_onebot_ws_connect_without_api_key():
    client = TestClient(create_app())
    with client.websocket_connect("/onebot/v11/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "post_type": "meta_event",
                    "meta_event_type": "lifecycle",
                    "sub_type": "connect",
                    "self_id": 12345,
                    "time": 1,
                }
            )
        )


def test_onebotv11_alias_path():
    client = TestClient(create_app())
    with client.websocket_connect("/OneBotv11") as ws:
        assert ws is not None
