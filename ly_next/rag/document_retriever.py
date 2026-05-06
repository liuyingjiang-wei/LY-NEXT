from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger
from ly_next.rag.chunking import chunk_text
from ly_next.rag.embedding_config import resolve_embedding_http_config
from ly_next.rag.embeddings import fetch_embeddings
from ly_next.rag.similarity import cosine_similarity, jaccard_similarity

logger = get_logger(__name__)


class DocumentRetriever:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._vectors: list[list[float]] | None = None
        self._loaded_path = ""
        self._lancedb_sig = ""
        self._lancedb_disabled = False
        self._warned_empty_path = False
        self._configured_once = False

    def configure(self) -> None:
        raw = str(config.get("agent.rag.documents_path", "") or "").strip()
        self._chunks = []
        self._vectors = None
        self._loaded_path = raw
        self._configured_once = True
        if not raw:
            if bool(config.get("agent.rag.enabled", False)) and not self._warned_empty_path:
                self._warned_empty_path = True
                logger.warning(
                    "[rag.docs] agent.rag.documents_path is empty; document retrieval is disabled."
                )
            return
        self._warned_empty_path = False

        root = get_project_root()
        target = Path(raw)
        if not target.is_absolute():
            target = root / target

        texts: list[str] = []
        if target.is_file():
            texts.append(_read_file(target))
        elif target.is_dir():
            for p in sorted(target.rglob("*")):
                if p.is_file() and p.suffix.lower() in {".md", ".txt", ".markdown"}:
                    texts.append(_read_file(p))
        else:
            logger.warning("[rag.docs] Path not found: %s", target)

        chunk_size = int(config.get("agent.rag.chunk_size", 900) or 900)
        overlap = int(config.get("agent.rag.chunk_overlap", 120) or 120)
        for t in texts:
            for c in chunk_text(t, chunk_size, overlap):
                if c:
                    self._chunks.append(c)

    async def retrieve_formatted(self, user_query: str) -> str:
        if not config.get("agent.rag.enabled", False):
            return ""
        path_cfg = str(config.get("agent.rag.documents_path", "") or "").strip()
        if not self._configured_once or self._loaded_path != path_cfg:
            self.configure()
        if not self._chunks or not user_query.strip():
            return ""

        top_k = int(config.get("agent.rag.top_k", 5) or 5)
        min_sim = float(config.get("agent.rag.min_similarity", 0.12) or 0.0)
        use_emb = bool(config.get("agent.rag.use_embeddings", True))

        if use_emb:
            try:
                ranked = await self._rank_embedding(user_query)
            except Exception as e:
                msg = str(e).strip() or repr(e)
                logger.warning(
                    "[rag.docs] Embedding retrieve failed, fallback lexical (%s): %s",
                    type(e).__name__,
                    msg,
                )
                ranked = self._rank_lexical(user_query)
        else:
            ranked = self._rank_lexical(user_query)

        picked = [(s, ch) for s, ch in ranked if s >= min_sim][:top_k]
        if not picked and ranked and ranked[0][0] > 0:
            picked = ranked[:1]
        if not picked:
            return ""

        parts = []
        for i, (score, ch) in enumerate(picked, 1):
            parts.append(f"片段{i}（相关度 {score:.2f}）\n{ch}")
        return "\n\n---\n\n".join(parts)

    def _rank_lexical(self, user_query: str) -> list[tuple[float, str]]:
        ranked: list[tuple[float, str]] = []
        for ch in self._chunks:
            ranked.append((jaccard_similarity(user_query, ch), ch))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    async def _rank_embedding(self, user_query: str) -> list[tuple[float, str]]:
        emb_cfg = config.get("agent.rag.embedding", {}) or {}
        if not isinstance(emb_cfg, dict):
            emb_cfg = {}
        hp = resolve_embedding_http_config(emb_cfg, config.get)
        model = hp["model"]
        api_key = hp["api_key"]
        base_url = hp["base_url"]
        timeout = hp["timeout"]
        auth_mode = hp["auth_mode"]
        auth_header_name = hp["auth_header_name"]
        extra_h = hp["extra_headers"]
        task_q = hp.get("task_query")
        task_p = hp.get("task_passage")
        dims = hp.get("dimensions")
        dim_opt: int | None = None
        if dims is not None:
            try:
                di = int(dims)
                dim_opt = di if di > 0 else None
            except (TypeError, ValueError):
                dim_opt = None
        xbody = hp.get("extra_body") if isinstance(hp.get("extra_body"), dict) else None

        if self._vectors is None or len(self._vectors) != len(self._chunks):
            batch = 32
            all_vec: list[list[float]] = []
            for i in range(0, len(self._chunks), batch):
                sub = self._chunks[i : i + batch]
                part = await fetch_embeddings(
                    sub,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                    auth_mode=auth_mode,
                    auth_header_name=auth_header_name,
                    extra_headers=extra_h,
                    task=str(task_p) if task_p else None,
                    dimensions=dim_opt,
                    extra_body=xbody,
                )
                all_vec.extend(part)
            self._vectors = all_vec

        self._ensure_lancedb_store()

        q_vecs = await fetch_embeddings(
            [user_query],
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            auth_mode=auth_mode,
            auth_header_name=auth_header_name,
            extra_headers=extra_h,
            task=str(task_q) if task_q else None,
            dimensions=dim_opt,
            extra_body=xbody,
        )
        if not q_vecs:
            return self._rank_lexical(user_query)
        qv = q_vecs[0]

        ranked_lancedb = self._query_lancedb(qv)
        if ranked_lancedb:
            return ranked_lancedb

        ranked: list[tuple[float, str]] = []
        for ch, vec in zip(self._chunks, self._vectors or [], strict=False):
            ranked.append((cosine_similarity(qv, vec), ch))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    def _vector_store_cfg(self) -> dict[str, Any]:
        raw = config.get("agent.rag.vector_store", {}) or {}
        return raw if isinstance(raw, dict) else {}

    def _ensure_lancedb_store(self) -> None:
        if self._lancedb_disabled:
            return
        vs = self._vector_store_cfg()
        if not bool(vs.get("enabled", True)):
            return
        backend = str(vs.get("backend") or "lancedb").strip().lower()
        if backend != "lancedb":
            return
        if not self._chunks or not self._vectors:
            return

        sig = self._build_lancedb_sig()
        if sig == self._lancedb_sig:
            return

        try:
            import lancedb  # type: ignore
        except Exception as e:
            logger.warning("[rag.docs] LanceDB unavailable, fallback to in-memory vectors: %s", e)
            self._lancedb_disabled = True
            return

        db_uri, table_name = self._resolve_lancedb_paths(vs)
        Path(db_uri).mkdir(parents=True, exist_ok=True)

        rows = [
            {"id": idx, "text": ch, "vector": vec}
            for idx, (ch, vec) in enumerate(zip(self._chunks, self._vectors, strict=False))
            if isinstance(vec, list) and vec
        ]
        if not rows:
            return
        try:
            db = lancedb.connect(db_uri)
            db.create_table(table_name, data=rows, mode="overwrite")
            self._lancedb_sig = sig
            logger.info(
                "[rag.docs] LanceDB table refreshed: %s (rows=%s, uri=%s)",
                table_name,
                len(rows),
                db_uri,
            )
        except Exception as e:
            logger.warning("[rag.docs] LanceDB write failed, fallback to in-memory vectors: %s", e)

    def _query_lancedb(self, query_vec: list[float]) -> list[tuple[float, str]]:
        if not query_vec or self._lancedb_disabled:
            return []
        vs = self._vector_store_cfg()
        if not bool(vs.get("enabled", True)):
            return []
        backend = str(vs.get("backend") or "lancedb").strip().lower()
        if backend != "lancedb":
            return []
        if not self._lancedb_sig:
            return []
        try:
            import lancedb  # type: ignore
        except Exception:
            self._lancedb_disabled = True
            return []

        db_uri, table_name = self._resolve_lancedb_paths(vs)
        limit = max(1, int(config.get("agent.rag.top_k", 5) or 5) * 3)
        try:
            db = lancedb.connect(db_uri)
            table = db.open_table(table_name)
            rows = table.search(query_vec).limit(limit).to_list()
        except Exception as e:
            logger.warning("[rag.docs] LanceDB query failed, fallback to in-memory vectors: %s", e)
            return []

        ranked: list[tuple[float, str]] = []
        for r in rows or []:
            text = str(r.get("text") or "")
            if not text:
                continue
            try:
                d = float(r.get("_distance", 1.0))
            except (TypeError, ValueError):
                d = 1.0
            score = max(0.0, 1.0 - d)
            ranked.append((score, text))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    def _resolve_lancedb_paths(self, vs: dict[str, Any]) -> tuple[str, str]:
        root = get_project_root()
        uri_raw = str(vs.get("uri") or "data/ly_next/lancedb").strip()
        p = Path(uri_raw)
        if not p.is_absolute():
            p = root / p
        table_name = str(vs.get("table") or "rag_chunks").strip() or "rag_chunks"
        return str(p), table_name

    def _build_lancedb_sig(self) -> str:
        h = hashlib.sha256()
        h.update(str(len(self._chunks)).encode("utf-8"))
        if self._chunks:
            h.update(self._chunks[0][:400].encode("utf-8", errors="ignore"))
            h.update(self._chunks[-1][:400].encode("utf-8", errors="ignore"))
        vlen = len(self._vectors or [])
        h.update(str(vlen).encode("utf-8"))
        if self._vectors:
            h.update(str(len(self._vectors[0])).encode("utf-8"))
        return h.hexdigest()


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("[rag.docs] Skip %s: %s", path, e)
        return ""


_retriever: DocumentRetriever | None = None


def get_document_retriever() -> DocumentRetriever:
    global _retriever
    if _retriever is None:
        _retriever = DocumentRetriever()
    return _retriever


def reset_document_retriever() -> None:
    global _retriever
    _retriever = None
