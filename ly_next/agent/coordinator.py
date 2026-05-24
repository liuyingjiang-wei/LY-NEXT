from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.prompt_augment import last_user_query
from ly_next.agent.react import ReactAgent
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.run_telemetry import emit_run_event, set_run_loop_kind

logger = get_logger(__name__)


def _json_dict_from_llm(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t, flags=re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        m2 = re.search(r"(\{[\s\S]*\})", t)
        if m2:
            t = m2.group(1)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _coordinator_cfg() -> dict[str, Any]:
    raw = config.get("agent.coordinator", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _normalize_agents(raw: dict[str, Any], *, max_agents: int) -> list[dict[str, str]]:
    agents_raw = raw.get("agents")
    if not isinstance(agents_raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in agents_raw[:max_agents]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("id") or "worker").strip()[:64]
        role = str(row.get("role") or "assistant").strip()[:400]
        focus = str(row.get("focus") or row.get("instruction") or "").strip()[:1200]
        if name:
            out.append({"name": name, "role": role, "focus": focus})
    return _dedupe_agent_names(out)


def _dedupe_agent_names(agents: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for a in agents:
        base = a["name"]
        n = base
        k = 2
        while n.lower() in seen:
            n = f"{base[:56]}_{k}"
            k += 1
        seen.add(n.lower())
        out.append({**a, "name": n})
    return out


def _execution_order_from_parsed(parsed: dict[str, Any]) -> str:
    raw = str(parsed.get("execution_order") or "sequential").strip().lower()
    return "parallel" if raw == "parallel" else "sequential"


async def _decompose(
    deps: AgentDeps,
    question: str,
    *,
    max_agents: int,
    max_tokens: int,
    retries: int,
) -> tuple[list[dict[str, str]], str]:
    q = (question or "").strip()[:12000]
    base_prompt = (
        f"You split work into at most {max_agents} specialists; prefer 1 when a single pass suffices, "
        f"otherwise 2–{max_agents}. Each specialist must have a distinct focus.\n"
        '"execution_order": "sequential" — later specialists may rely on summarized prior output in order.\n'
        '"execution_order": "parallel" — use ONLY when every specialist can complete from the user task alone '
        "(e.g. unrelated code areas, independent checks). Never parallel if a step must read another specialist's "
        "conclusions first.\n"
        "Output a single JSON object only (no markdown): "
        '{"execution_order":"sequential"|"parallel",'
        '"agents":[{"name":"snake_case_id","role":"one line","focus":"deliverable scope"}]}\n'
        f"Task:\n{q}"
    )
    strict = (
        "The previous response was invalid. Output ONLY valid JSON starting with { "
        'matching: {"execution_order":"sequential"|"parallel",'
        '"agents":[{"name":"...","role":"...","focus":"..."}]} — non-empty name strings.\nTask:\n'
        + q
    )
    for attempt in range(max(0, retries) + 1):
        prompt = base_prompt if attempt == 0 else strict
        try:
            text = await deps.call_llm_limited(prompt, max_tokens=max_tokens, temperature=0.15)
            parsed = _json_dict_from_llm(text or "") or {}
            order = _execution_order_from_parsed(parsed)
            agents = _normalize_agents(parsed, max_agents=max_agents)
            if agents:
                if order == "parallel" and len(agents) < 2:
                    order = "sequential"
                if len(agents) > 1:
                    logger.info(
                        "[coordinator] decomposed into %s specialists (%s)",
                        len(agents),
                        order,
                    )
                return agents, order
        except Exception as e:
            logger.warning("[coordinator] decompose attempt %s failed: %s", attempt + 1, e)
    return [], "sequential"


async def _compress_handoff(deps: AgentDeps, prior: str, *, budget: int, max_tokens: int) -> str:
    prior = (prior or "").strip()
    if len(prior) <= budget:
        return prior
    prompt = (
        f"Compress the following specialist handoff to at most {budget} characters. "
        "Keep facts, decisions, errors, tool outcomes; drop repetition.\n---\n" + prior[:50000]
    )
    try:
        out = (
            await deps.call_llm_limited(prompt, max_tokens=max(96, max_tokens), temperature=0.2)
        ).strip()
        return out[:budget] if out else prior[-budget:]
    except Exception as e:
        logger.warning("[coordinator] handoff compress failed: %s", e)
        return prior[-budget:]


def _delegate_system(
    agent: dict[str, str],
    prior: str,
    *,
    handoff_max_chars: int,
    parallel_branch: bool = False,
) -> dict[str, Any]:
    block = (
        f"You are specialist 「{agent['name']}」.\nRole: {agent['role']}\n"
        f"Focus: {agent['focus']}\n"
        "Produce concise, actionable output for downstream merging.\n"
    )
    if parallel_branch:
        block += (
            "\nOther specialists run in parallel on disjoint slices — do not assume their results; "
            "stay within your focus.\n"
        )
    elif prior.strip():
        block += f"\nPrior specialists output (reference):\n{prior[:handoff_max_chars]}\n"
    return {"role": "system", "content": block}


def _inject_messages(
    base: list[dict[str, Any]], extra_system: dict[str, Any]
) -> list[dict[str, Any]]:
    return [extra_system, *[dict(m) for m in base]]


async def _synthesize(
    deps: AgentDeps,
    question: str,
    reports: list[dict[str, str]],
    *,
    max_tokens: int,
    body_max_chars: int,
) -> str:
    lines = [f"### {r['name']}\n{r['output']}" for r in reports]
    body = "\n\n".join(lines)[:body_max_chars]
    prompt = (
        "Merge specialist reports into one user-facing answer.\n"
        "You must reconcile overlaps and contradictions explicitly; state uncertainties.\n"
        "Do not paste section headers verbatim unless they help the user; prefer a unified narrative.\n"
        f"Original task:\n{question[:4000]}\n---\nReports:\n{body}"
    )
    return (
        await deps.call_llm_limited(
            prompt, max_tokens=max(256, min(max_tokens, 8192)), temperature=0.35
        )
    ).strip()


async def _run_parallel_delegates(
    messages: list[dict[str, Any]],
    agents: list[dict[str, str]],
    sub_deps: AgentDeps,
    lim: dict[str, Any],
) -> list[dict[str, str]]:
    sem = asyncio.Semaphore(max(1, int(lim["max_parallel"])))

    async def one(agent: dict[str, str]) -> dict[str, str]:
        async with sem:
            msgs = _inject_messages(
                messages,
                _delegate_system(
                    agent,
                    "",
                    handoff_max_chars=int(lim["handoff_max"]),
                    parallel_branch=True,
                ),
            )
            worker = ReactAgent(sub_deps)
            text = (await worker.run(msgs)).strip()
            return {"name": agent["name"], "output": text}

    return list(await asyncio.gather(*[one(a) for a in agents]))


def deps_max(deps: AgentDeps) -> int:
    return max(2, int(deps.max_steps or 6))


def _cfg_limits(deps: AgentDeps) -> dict[str, Any]:
    c = _coordinator_cfg()
    max_agents = max(1, min(int(c.get("max_agents", 3) or 3), 8))
    per_steps = max(2, min(int(c.get("max_steps_per_delegate", 5) or 5), deps_max(deps)))
    dec_toks = max(160, min(int(c.get("decompose_max_tokens", 768) or 768), 2048))
    retries = max(0, min(int(c.get("decompose_retries", 1) or 1), 3))
    handoff_max = max(1500, min(int(c.get("handoff_max_chars", 7000) or 7000), 50000))
    synth_toks = max(256, min(int(c.get("synthesize_max_tokens", 2048) or 2048), 8192))
    body_max = max(4000, min(int(c.get("synthesize_body_max_chars", 24000) or 24000), 120000))
    compress_handoff = bool(c.get("compress_handoff", False))
    handoff_compress_toks = max(
        64, min(int(c.get("handoff_compress_max_tokens", 384) or 384), 1024)
    )
    parallel_delegates = bool(c.get("parallel_delegates", True))
    max_parallel = max(1, min(int(c.get("max_parallel_delegates", 4) or 4), 16))
    return {
        "max_agents": max_agents,
        "per_steps": per_steps,
        "dec_toks": dec_toks,
        "retries": retries,
        "handoff_max": handoff_max,
        "synth_toks": synth_toks,
        "body_max": body_max,
        "compress_handoff": compress_handoff,
        "handoff_compress_toks": handoff_compress_toks,
        "parallel_delegates": parallel_delegates,
        "max_parallel": max_parallel,
    }


class CoordinatorAgent:
    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        self.deps = deps if deps is not None else create_agent_deps(**kwargs)

    async def run(self, messages: list[dict[str, Any]]) -> str:
        set_run_loop_kind("coordinator")
        lim = _cfg_limits(self.deps)

        question = last_user_query(messages)
        if not question:
            c0 = (messages[0].get("content", "") if messages else "") if messages else ""
            question = c0 if isinstance(c0, str) else json.dumps(c0, ensure_ascii=False)

        agents, execution_order = await _decompose(
            self.deps,
            question,
            max_agents=lim["max_agents"],
            max_tokens=lim["dec_toks"],
            retries=lim["retries"],
        )
        emit_run_event(
            "coordinator_plan",
            {"agents": len(agents), "execution_order": execution_order},
        )
        if not lim["parallel_delegates"]:
            execution_order = "sequential"
        base = replace(self.deps, reasoning_mode="react")
        if len(agents) == 0:
            return await ReactAgent(base).run(messages)
        if len(agents) == 1:
            msgs = _inject_messages(
                messages, _delegate_system(agents[0], "", handoff_max_chars=lim["handoff_max"])
            )
            return await ReactAgent(base).run(msgs)

        sub_deps = replace(self.deps, max_steps=lim["per_steps"], reasoning_mode="react")

        if execution_order == "parallel":
            reports = await _run_parallel_delegates(messages, agents, sub_deps, lim)
            return await _synthesize(
                self.deps,
                question,
                reports,
                max_tokens=int(lim["synth_toks"]),
                body_max_chars=int(lim["body_max"]),
            )

        prior = ""
        reports: list[dict[str, str]] = []

        for agent in agents:
            handoff = prior
            if lim["compress_handoff"] and len(handoff) > int(lim["handoff_max"]):
                handoff = await _compress_handoff(
                    self.deps,
                    handoff,
                    budget=int(lim["handoff_max"]),
                    max_tokens=int(lim["handoff_compress_toks"]),
                )
            msgs = _inject_messages(
                messages,
                _delegate_system(agent, handoff, handoff_max_chars=int(lim["handoff_max"])),
            )
            worker = ReactAgent(sub_deps)
            out = (await worker.run(msgs)).strip()
            reports.append({"name": agent["name"], "output": out})
            prior = "\n\n".join(f"### {r['name']}\n{r['output']}" for r in reports)

        return await _synthesize(
            self.deps,
            question,
            reports,
            max_tokens=int(lim["synth_toks"]),
            body_max_chars=int(lim["body_max"]),
        )

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        set_run_loop_kind("coordinator")
        lim = _cfg_limits(self.deps)

        question = last_user_query(messages)
        if not question:
            c0 = (messages[0].get("content", "") if messages else "") if messages else ""
            question = c0 if isinstance(c0, str) else json.dumps(c0, ensure_ascii=False)

        yield {"type": "status", "phase": "coordinator", "detail": "分解子任务…"}

        agents, execution_order = await _decompose(
            self.deps,
            question,
            max_agents=lim["max_agents"],
            max_tokens=lim["dec_toks"],
            retries=lim["retries"],
        )
        emit_run_event(
            "coordinator_plan",
            {"agents": len(agents), "execution_order": execution_order},
        )
        if not lim["parallel_delegates"]:
            execution_order = "sequential"
        yield {
            "type": "node",
            "node": "coordinator_plan",
            "data": {"agents": agents, "execution_order": execution_order},
        }

        base = replace(self.deps, reasoning_mode="react")
        if len(agents) == 0:
            yield {"type": "status", "phase": "coordinator", "detail": "执行 ReAct…"}
            async for ev in ReactAgent(base).run_stream(messages):
                yield ev
            return
        if len(agents) == 1:
            yield {
                "type": "status",
                "phase": "coordinator",
                "detail": f"单专家「{agents[0]['name']}」…",
            }
            msgs = _inject_messages(
                messages,
                _delegate_system(agents[0], "", handoff_max_chars=lim["handoff_max"]),
            )
            async for ev in ReactAgent(base).run_stream(msgs):
                yield ev
            return

        sub_deps = replace(self.deps, max_steps=lim["per_steps"], reasoning_mode="react")

        if execution_order == "parallel":
            yield {
                "type": "status",
                "phase": "delegate",
                "detail": f"并行调度 {len(agents)} 路专家（≤{lim['max_parallel']} 并发）…",
            }
            reports = await _run_parallel_delegates(messages, agents, sub_deps, lim)
            for r in reports:
                yield {"type": "node", "node": "coordinator_delegate", "data": r}
            yield {"type": "status", "phase": "coordinator", "detail": "汇总专家输出…"}
            text = await _synthesize(
                self.deps,
                question,
                reports,
                max_tokens=int(lim["synth_toks"]),
                body_max_chars=int(lim["body_max"]),
            )
            yield {"type": "final", "content": text}
            return

        prior = ""
        reports: list[dict[str, str]] = []

        for agent in agents:
            yield {
                "type": "status",
                "phase": "delegate",
                "detail": f"执行专家「{agent['name']}」…",
            }
            handoff = prior
            if lim["compress_handoff"] and len(handoff) > int(lim["handoff_max"]):
                handoff = await _compress_handoff(
                    self.deps,
                    handoff,
                    budget=int(lim["handoff_max"]),
                    max_tokens=int(lim["handoff_compress_toks"]),
                )
            msgs = _inject_messages(
                messages,
                _delegate_system(agent, handoff, handoff_max_chars=int(lim["handoff_max"])),
            )
            worker = ReactAgent(sub_deps)
            out = (await worker.run(msgs)).strip()
            reports.append({"name": agent["name"], "output": out})
            prior = "\n\n".join(f"### {r['name']}\n{r['output']}" for r in reports)

        yield {"type": "status", "phase": "coordinator", "detail": "汇总专家输出…"}
        text = await _synthesize(
            self.deps,
            question,
            reports,
            max_tokens=int(lim["synth_toks"]),
            body_max_chars=int(lim["body_max"]),
        )
        yield {"type": "final", "content": text}
