from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger
from ly_next.rag.embedding_config import resolve_embedding_http_config
from ly_next.rag.embeddings import fetch_embeddings
from ly_next.rag.similarity import cosine_similarity, jaccard_similarity

logger = get_logger(__name__)

_EMBEDDINGS_404_HINT_LOGGED = [False]


@dataclass
class _Example:
    query: str
    response: str


def _builtin_examples_path() -> Path:
    return Path(__file__).resolve().parent.parent / "builtin" / "agent_examples.yaml"


def _load_examples(path_str: str | None) -> list[_Example]:
    raw_path = (path_str or "").strip()
    paths: list[Path] = []
    if raw_path:
        p = Path(raw_path)
        if not p.is_absolute():
            p = get_project_root() / p
        paths.append(p)
    paths.append(_builtin_examples_path())

    for p in paths:
        if not p.is_file():
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("[rag.examples] Failed to read %s: %s", p, e)
            continue
        items = data.get("examples") if isinstance(data, dict) else data
        if not isinstance(items, list):
            continue
        out: list[_Example] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            q = str(it.get("query") or it.get("question") or "").strip()
            r = str(it.get("response") or it.get("answer") or "").strip()
            if q and r:
                out.append(_Example(query=q, response=r))
        if out:
            return out
    return []


class ExampleSelector:
    def __init__(self) -> None:
        self._examples: list[_Example] = []
        self._vectors: list[list[float]] | None = None
        self._source_tag = ""

    def configure(self) -> None:
        path = config.get("agent.context.examples_path", "") or ""
        self._examples = _load_examples(str(path) if path else None)
        self._vectors = None
        self._source_tag = str(path) if path else "builtin"

    async def select_formatted(self, user_query: str) -> str:
        if not config.get("agent.context.enabled", True):
            return ""
        if not self._examples:
            self.configure()
        if not self._examples or not user_query.strip():
            return ""

        top_k = int(config.get("agent.context.top_k", 3) or 3)
        min_sim = float(config.get("agent.context.min_similarity", 0.15) or 0.0)
        use_emb = bool(config.get("agent.context.use_embeddings", True))

        scored: list[tuple[float, _Example]] = []
        if use_emb:
            try:
                scored = await self._rank_embedding(user_query)
            except Exception as e:
                msg = str(e).strip() or repr(e)
                if (
                    "404" in msg
                    and "embeddings" in msg.lower()
                    and not _EMBEDDINGS_404_HINT_LOGGED[0]
                ):
                    _EMBEDDINGS_404_HINT_LOGGED[0] = True
                    logger.warning(
                        "[rag.examples] Embeddings 404（常见于聊天网关未实现 /embeddings）。"
                        "请把 agent.rag.embedding.config_ref 设为 rag_embedding_llm（Jina），"
                        "或设置 agent.context.use_embeddings: false。"
                    )
                logger.warning(
                    "[rag.examples] Embedding rank failed, fallback lexical (%s): %s",
                    type(e).__name__,
                    msg,
                )
                scored = self._rank_lexical(user_query)
        else:
            scored = self._rank_lexical(user_query)

        picked = [(s, ex) for s, ex in scored if s >= min_sim][:top_k]
        if not picked and scored and scored[0][0] > 0:
            picked = scored[:1]

        if not picked:
            return ""

        lines = []
        for i, (score, ex) in enumerate(picked, 1):
            lines.append(f"示例{i}（相似度 {score:.2f}）\n问：{ex.query}\n答：{ex.response}")
        return "\n\n".join(lines)

    def _rank_lexical(self, user_query: str) -> list[tuple[float, _Example]]:
        scored: list[tuple[float, _Example]] = []
        for ex in self._examples:
            s = jaccard_similarity(user_query, ex.query)
            scored.append((s, ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    async def _rank_embedding(self, user_query: str) -> list[tuple[float, _Example]]:
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

        if self._vectors is None or len(self._vectors) != len(self._examples):
            texts = [ex.query for ex in self._examples]
            self._vectors = await fetch_embeddings(
                texts,
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

        q_vec_list = await fetch_embeddings(
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
        if not q_vec_list:
            return self._rank_lexical(user_query)
        qv = q_vec_list[0]

        scored: list[tuple[float, _Example]] = []
        for ex, vec in zip(self._examples, self._vectors or [], strict=False):
            scored.append((cosine_similarity(qv, vec), ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored


_selector: ExampleSelector | None = None


def get_example_selector() -> ExampleSelector:
    global _selector
    if _selector is None:
        _selector = ExampleSelector()
    return _selector


def reset_example_selector() -> None:
    global _selector
    _selector = None
