from ly_next.messaging.image_handler import (
    build_mixed_message,
    extract_image_urls_from_tool_results,
    parse_image_tags,
)


def test_parse_image_tags():
    text = "看这只猫 [image:https://example.com/a.png] 可爱吗？"
    parts, urls = parse_image_tags(text)
    assert urls == ["https://example.com/a.png"]
    assert len(parts) == 3
    assert parts[1].type == "image"


def test_build_from_tool_results():
    tool_results = [
        {
            "tool": "generate_image",
            "result": {
                "success": True,
                "result": '{"status": "ok", "image_url": "https://cdn.example/x.png"}',
            },
        }
    ]
    mixed = build_mixed_message("画好了", tool_results)
    assert mixed.has_images
    assert "https://cdn.example/x.png" in mixed.image_urls()


def test_build_merges_tags_and_tools():
    text = "第一张 [image:https://a.com/1.jpg]"
    tool_results = [
        {
            "tool": "search_images",
            "result": {
                "success": True,
                "result": '{"status": "ok", "image_urls": ["https://b.com/2.jpg"]}',
            },
        }
    ]
    mixed = build_mixed_message(text, tool_results)
    urls = mixed.image_urls()
    assert "https://a.com/1.jpg" in urls
    assert "https://b.com/2.jpg" in urls


def test_extract_urls_from_nested_dict_result():
    tool_results = [
        {
            "tool": "generate_image",
            "result": {
                "success": True,
                "result": {"status": "ok", "image_url": "https://cdn.example/y.png"},
            },
        }
    ]
    assert extract_image_urls_from_tool_results(tool_results) == ["https://cdn.example/y.png"]
