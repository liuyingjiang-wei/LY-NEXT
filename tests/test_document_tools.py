from __future__ import annotations

import pytest

from ly_next.tools.document_tools import generate_docx, generate_xlsx, generate_pptx
from ly_next.tools.export_paths import resolve_export_path


def _patch_exports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("ly_next.tools.export_paths.exports_dir", lambda: tmp_path)
    monkeypatch.setattr("ly_next.tools.document_tools.exports_dir", lambda: tmp_path)


@pytest.mark.asyncio
async def test_generate_docx_creates_downloadable_file(tmp_path, monkeypatch):
    _patch_exports_dir(monkeypatch, tmp_path)
    result = await generate_docx(
        title="测试文档",
        sections=[{"heading": "第一节", "paragraphs": ["段落 A", "段落 B"]}],
        filename="demo",
    )
    assert result.success is True
    name = result.result["filename"]
    assert name.endswith(".docx")
    assert result.result["download_url"] == f"/api/exports/{name}"
    assert (tmp_path / name).is_file()
    monkeypatch.setattr("ly_next.tools.export_paths.exports_dir", lambda: tmp_path)
    assert resolve_export_path(name) is not None


@pytest.mark.asyncio
async def test_generate_xlsx_creates_downloadable_file(tmp_path, monkeypatch):
    _patch_exports_dir(monkeypatch, tmp_path)
    result = await generate_xlsx(
        headers=["名称", "数量"],
        rows=[["苹果", 3], ["香蕉", 5]],
        sheet_name="水果",
    )
    assert result.success is True
    name = result.result["filename"]
    assert (tmp_path / name).is_file()


@pytest.mark.asyncio
async def test_generate_pptx_creates_downloadable_file(tmp_path, monkeypatch):
    _patch_exports_dir(monkeypatch, tmp_path)
    result = await generate_pptx(
        title="季度汇报",
        slides=[{"title": "概览", "bullets": ["增长 12%", "新客户 40"]}],
    )
    assert result.success is True
    name = result.result["filename"]
    assert (tmp_path / name).is_file()
