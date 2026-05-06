from __future__ import annotations

from pathlib import Path

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

    def configure(self) -> None:
        raw = str(config.get("agent.rag.documents_path", "") or "").strip()
        self._chunks = []
        self._vectors = None
        self._loaded_path = raw
        if not raw:
            return

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
        if self._loaded_path != path_cfg:
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
                logger.debug("[rag.docs] Embedding retrieve failed, fallback lexical: %s", e)
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
                )
                all_vec.extend(part)
            self._vectors = all_vec

        q_vecs = await fetch_embeddings(
            [user_query],
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            auth_mode=auth_mode,
            auth_header_name=auth_header_name,
            extra_headers=extra_h,
        )
        if not q_vecs:
            return self._rank_lexical(user_query)
        qv = q_vecs[0]

        ranked: list[tuple[float, str]] = []
        for ch, vec in zip(self._chunks, self._vectors or [], strict=False):
            ranked.append((cosine_similarity(qv, vec), ch))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked


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
