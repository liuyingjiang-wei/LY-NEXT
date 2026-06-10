#!/usr/bin/env -S uv run python
"""Run RAG golden-set evaluation (Recall@k / Hit@1 / must_contain)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_golden(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("golden file must be a JSON array")
    return data


def _hit_sources(hits: list[dict], expected: list[str]) -> bool:
    if not expected:
        return True
    got = {str(h.get("source") or "") for h in hits}
    return any(any(exp in src for src in got) for exp in expected)


def _must_contain(hits: list[dict], needles: list[str]) -> bool:
    if not needles:
        return True
    blob = "\n".join(str(h.get("text") or "") for h in hits).lower()
    return all(n.lower() in blob for n in needles)


async def _run_eval(golden_path: Path, top_k: int) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from ly_next.core.config import config
    from ly_next.rag.document_retriever import get_document_retriever, reset_document_retriever

    reset_document_retriever()
    retriever = get_document_retriever()
    cases = _load_golden(golden_path)

    recall_hits = 0
    hit1 = 0
    contain_ok = 0
    rows: list[dict] = []

    for case in cases:
        q = str(case.get("query") or "").strip()
        if not q:
            continue
        payload = await retriever.retrieve_results(q, top_k=top_k)
        hits = list(payload.get("hits") or [])
        expected = [str(x) for x in (case.get("expected_sources") or [])]
        needles = [str(x) for x in (case.get("must_contain") or [])]

        src_ok = _hit_sources(hits, expected)
        contain = _must_contain(hits, needles)
        top1_ok = bool(hits) and src_ok and contain

        if src_ok:
            recall_hits += 1
        if hits and _hit_sources(hits[:1], expected) and _must_contain(hits[:1], needles):
            hit1 += 1
        if contain:
            contain_ok += 1

        rows.append(
            {
                "id": case.get("id"),
                "query": q,
                "hits": len(hits),
                "source_ok": src_ok,
                "contain_ok": contain,
                "top1_ok": top1_ok,
            }
        )

    n = max(len(rows), 1)
    return {
        "cases": len(rows),
        "top_k": top_k,
        "rag_enabled": bool(config.get("agent.rag.enabled", False)),
        "documents_path": config.get("agent.rag.documents_path", ""),
        "recall_at_k": round(recall_hits / n, 4),
        "hit_at_1": round(hit1 / n, 4),
        "must_contain_rate": round(contain_ok / n, 4),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval against golden set")
    parser.add_argument(
        "--golden",
        type=Path,
        default=ROOT / "tests" / "rag_eval" / "golden.json",
    )
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    report = asyncio.run(_run_eval(args.golden, args.top_k))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
