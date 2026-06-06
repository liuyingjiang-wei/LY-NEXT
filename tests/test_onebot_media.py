from ly_next.messaging.onebot_media import image_segment, normalize_onebot_image_file


def test_normalize_http_url():
    url = "https://example.com/a.png"
    assert normalize_onebot_image_file(url) == url


def test_normalize_data_url_to_base64_protocol():
    ref = "data:image/png;base64,abcd1234"
    assert normalize_onebot_image_file(ref) == "base64://abcd1234"


def test_image_segment_http():
    seg = image_segment("https://cdn.example/x.jpg")
    assert seg["type"] == "image"
    assert seg["data"]["file"] == "https://cdn.example/x.jpg"
    assert seg["data"].get("url") == "https://cdn.example/x.jpg"
