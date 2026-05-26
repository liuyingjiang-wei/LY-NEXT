from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.rag import document_retriever as dr


def test_resolve_documents_path_prefers_data_root_knowledge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = tmp_path / "proj"
    project.mkdir()
    data_root = project / "data" / "ly_next"
    knowledge = data_root / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "note.md").write_text("hello", encoding="utf-8")

    monkeypatch.setattr(dr, "get_project_root", lambda: project)
    monkeypatch.setattr(dr, "get_data_root", lambda: data_root)

    resolved = dr._resolve_documents_path("data/ly_next/knowledge")
    assert resolved == knowledge
    assert resolved.is_dir()
