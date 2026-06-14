"""Shared native ReAct step logic for direct loop and LangGraph nodes."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.agent.persona import combine_native_system_prefix
from ly_next.agent.prompt_augment import last_user_query
from ly_next.agent.react.helpers import (
    aborted,
    assistant_turn_from_response,
    inject_tool_manifest,
    length_continuation_user_text,
    merge_system_instruction,
    parse_openai_completion,
    preview_json,
    sanitize_dialog_messages,
)
from ly_next.agent.react.tool_exec import execute_native_tool_call
from ly_next.agent.streaming_tool_executor import StreamingToolExecutor
from ly_next.agent.tool_filter import get_openai_tools_for_deps
from ly_next.agent.turn_engine import iter_direct_answer
from ly_next.core.config import config
from ly_next.core.context_budget import (
    cumulative_budget_limit,
    effective_context_window_tokens,
    estimate_dialog_tokens,
    length_continuation_max,
    parse_completion_meta,
    prune_old_tool_message_contents,
)
from ly_next.core.logger import get_logger
from ly_next.core.run_graph import (
    NODE_DIRECT_ANSWER,
    NODE_EXECUTE_TOOLS,
    NODE_FINALIZE,
    NODE_REACT_STEP,
    emit_graph_edge,
    emit_graph_node_enter,
    emit_graph_node_exit,
)

logger = get_logger(__name__)


def eager_tool_dispatch_enabled() -> bool:
    if config.get("agent.eager_tool_dispatch") is not None:
        return bool(config.get("agent.eager_tool_dispatch"))
    return True


def graph_finish_final(*, iteration: int, outcome: str = "final") -> None:
    emit_graph_node_exit(NODE_REACT_STEP, iteration=iteration, outcome=outcome)
    emit_graph_edge(NODE_REACT_STEP, NODE_FINALIZE, iteration=iteration, reason=outcome)
    emit_graph_node_enter(NODE_FINALIZE)
    emit_graph_node_exit(NODE_FINALIZE, outcome="done")


def graph_begin_tool_phase(*, iteration: int, tool_names: list[str]) -> None:
    emit_graph_node_exit(
        NODE_REACT_STEP,
        iteration=iteration,
        outcome="tool_calls",
        tools=tool_names,
    )
    emit_graph_edge(
        NODE_REACT_STEP,
        NODE_EXECUTE_TOOLS,
        iteration=iteration,
        tools=tool_names,
    )
    emit_graph_node_enter(NODE_EXECUTE_TOOLS, iteration=iteration, tools=tool_names)


def graph_end_tool_phase(*, iteration: int) -> None:
    emit_graph_node_exit(NODE_EXECUTE_TOOLS, iteration=iteration, outcome="ok")
    emit_graph_edge(
        NODE_EXECUTE_TOOLS,
        NODE_REACT_STEP,
        iteration=iteration + 1,
        reason="loop",
    )


@dataclass
class NativeReactSession:
    deps: AgentDeps
    messages: list[dict[str, Any]]
    dialog: list[dict[str, Any]] = field(default_factory=list)
    openai_tools: list[dict[str, Any]] = field(default_factory=list)
    allowed_names: list[str] = field(default_factory=list)
    allowed_set: set[str] = field(default_factory=set)
    last_sig: str = ""
    same_sig_count: int = 0
    fail_streak: int = 0
    run_tag: str = field(default_factory=lambda: secrets.token_hex(6))
    budget_used: int = 0
    iteration: int = 0
    done: bool = False
    direct_only: bool = False
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    pending_executor: StreamingToolExecutor | None = None
    cap_ceiling: int = 0
    ctx_window: int = 0

    @classmethod
    def from_messages(cls, messages: list[dict[str, Any]], deps: AgentDeps) -> NativeReactSession:
        openai_tools, allowed_names, _objs = get_openai_tools_for_deps(deps)
        session = cls(
            deps=deps,
            messages=list(messages),
            openai_tools=list(openai_tools or []),
            allowed_names=list(allowed_names or []),
            allowed_set=set(allowed_names or []),
            cap_ceiling=cumulative_budget_limit(),
            ctx_window=effective_context_window_tokens(deps.model),
        )
        session.dialog = merge_system_instruction(
            sanitize_dialog_messages(list(messages)),
            persona_block=deps.persona_system_prefix or "",
        )
        if openai_tools:
            inject_tool_manifest(session.dialog, allowed_names)
            logger.info(
                "[agent.native] Registered tools exposed to model (%s): %s",
                len(allowed_names),
                ", ".join(allowed_names),
            )
        else:
            session.direct_only = True
        return session

    def to_state(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "dialog": self.dialog,
            "openai_tools": self.openai_tools,
            "allowed_names": self.allowed_names,
            "last_sig": self.last_sig,
            "same_sig_count": self.same_sig_count,
            "fail_streak": self.fail_streak,
            "run_tag": self.run_tag,
            "budget_used": self.budget_used,
            "iteration": self.iteration,
            "done": self.done,
            "direct_only": self.direct_only,
            "pending_tool_calls": self.pending_tool_calls,
            "phase": "done" if self.done else ("tools" if self.pending_tool_calls else "llm"),
        }

    @classmethod
    def from_state(cls, state: dict[str, Any], deps: AgentDeps) -> NativeReactSession:
        session = cls(
            deps=deps,
            messages=list(state.get("messages") or []),
            dialog=list(state.get("dialog") or []),
            openai_tools=list(state.get("openai_tools") or []),
            allowed_names=list(state.get("allowed_names") or []),
            allowed_set=set(state.get("allowed_names") or []),
            last_sig=str(state.get("last_sig") or ""),
            same_sig_count=int(state.get("same_sig_count") or 0),
            fail_streak=int(state.get("fail_streak") or 0),
            run_tag=str(state.get("run_tag") or secrets.token_hex(6)),
            budget_used=int(state.get("budget_used") or 0),
            iteration=int(state.get("iteration") or 0),
            done=bool(state.get("done")),
            direct_only=bool(state.get("direct_only")),
            pending_tool_calls=list(state.get("pending_tool_calls") or []),
            cap_ceiling=cumulative_budget_limit(),
            ctx_window=effective_context_window_tokens(deps.model),
        )
        return session

    async def iter_direct_answer(self) -> AsyncIterator[dict[str, Any]]:
        emit_graph_node_enter(NODE_DIRECT_ANSWER, reason="no_tools_visible")
        yield {
            "type": "status",
            "phase": "direct",
            "detail": "当前过滤条件下无可用工具，改为直接对话",
        }
        q = last_user_query(self.messages)
        if not q:
            q = "\n".join(
                f"{(m.get('role') or 'user')}: {m.get('content', '')}"
                for m in (self.messages or [])
            ).strip()
        prompt = (
            f"{combine_native_system_prefix(deps.persona_system_prefix or '')}\n\n"
            f"User request:\n{q}\n\nAnswer without tools."
        )
        async for ev in iter_direct_answer(
            self.deps,
            [{"role": "user", "content": prompt}],
            status_detail="直接回答",
        ):
            yield ev
        emit_graph_node_exit(NODE_DIRECT_ANSWER, outcome="done")
        self.done = True

    async def step_llm(self) -> AsyncIterator[dict[str, Any]]:
        deps = self.deps
        if self.done:
            return
        if aborted(deps):
            yield {"type": "final", "content": "（对话已由用户中断）"}
            self.done = True
            return
        if self.cap_ceiling > 0 and self.budget_used >= self.cap_ceiling:
            yield {
                "type": "final",
                "content": "Stopped: cumulative completion-token budget exhausted.",
            }
            self.done = True
            return

        iteration = self.iteration
        yield {
            "type": "status",
            "phase": "llm",
            "iteration": iteration,
            "detail": "请求模型（function calling / tool_calls）",
        }
        emit_graph_node_enter(NODE_REACT_STEP, iteration=iteration, phase="llm")
        self.dialog = prune_old_tool_message_contents(
            self.dialog, model=deps.model, max_output_tokens=deps.max_tokens
        )
        if deps.verbose:
            approx_in = estimate_dialog_tokens(self.dialog)
            if approx_in > self.ctx_window * 0.92:
                logger.warning(
                    "[agent.native] dialog ~%s est. tokens vs window %s (tool bodies may be pruned)",
                    approx_in,
                    self.ctx_window,
                )

        executor: StreamingToolExecutor | None = None
        if eager_tool_dispatch_enabled():
            executor = StreamingToolExecutor(
                deps,
                allowed_set=self.allowed_set,
                run_tag=self.run_tag,
                iteration=iteration,
                id_prefix="call",
            )

        try:
            cont_i = 0
            max_len_cont = length_continuation_max()
            resp: dict[str, Any] = {}
            raw_msg: dict[str, Any] | None = None
            tool_calls: list[dict[str, Any]] = []

            while True:
                if aborted(deps):
                    yield {"type": "final", "content": "（对话已由用户中断）"}
                    self.done = True
                    return

                streamed_parts: list[str] = []
                resp = {}
                raw_msg = None
                tool_calls = []

                async for stream_ev in deps.iter_chat_with_tools(self.dialog, self.openai_tools):
                    if stream_ev.get("type") == "think_chunk":
                        piece = str(stream_ev.get("content") or "")
                        if piece:
                            yield {"type": "think_chunk", "content": piece}
                    elif stream_ev.get("type") == "chunk":
                        piece = str(stream_ev.get("content") or "")
                        if piece:
                            streamed_parts.append(piece)
                            yield {"type": "chunk", "content": piece}
                    elif stream_ev.get("type") == "tool_call_ready" and executor is not None:
                        idx = int(stream_ev.get("index", 0))
                        tc = stream_ev.get("tool_call") or {}
                        start_ev = executor.note_sealed(idx, tc)
                        if start_ev is not None:
                            yield start_ev
                    elif stream_ev.get("type") == "completion":
                        resp = stream_ev.get("response") or {}
                        raw_msg, tool_calls = parse_openai_completion(resp)

                if raw_msg is None:
                    keys = list(resp.keys()) if isinstance(resp, dict) else []
                    logger.warning(
                        "[agent.native] Unrecognized chat completion shape (top-level keys=%s)",
                        keys[:20],
                    )
                    raise RuntimeError("unexpected completion payload")

                ct, _tt, fr = parse_completion_meta(resp)
                if ct is not None:
                    self.budget_used += ct
                else:
                    c0 = raw_msg.get("content")
                    s = c0 if isinstance(c0, str) else str(c0 or "")
                    self.budget_used += max(0, len(s) // 4)

                if self.cap_ceiling > 0 and self.budget_used >= self.cap_ceiling and not tool_calls:
                    content = raw_msg.get("content")
                    out = (
                        (content or "").strip()
                        if isinstance(content, str)
                        else str(content or "").strip()
                    )
                    if not out and streamed_parts:
                        out = "".join(streamed_parts).strip()
                    yield {"type": "status", "phase": "answer", "detail": "输出预算已达上限"}
                    graph_finish_final(iteration=iteration, outcome="budget_exhausted")
                    yield {
                        "type": "final",
                        "content": out or "Stopped: cumulative completion-token budget exhausted.",
                        "chunked": bool(streamed_parts),
                    }
                    self.done = True
                    return

                if tool_calls:
                    break

                content = raw_msg.get("content")
                out = (
                    (content or "").strip()
                    if isinstance(content, str)
                    else str(content or "").strip()
                )
                if not out and streamed_parts:
                    out = "".join(streamed_parts).strip()
                if fr in ("length", "max_tokens") and cont_i < max_len_cont:
                    yield {
                        "type": "status",
                        "phase": "llm",
                        "iteration": iteration,
                        "detail": f"输出因长度截断，续写 ({cont_i + 1}/{max_len_cont})",
                    }
                    self.dialog.append(assistant_turn_from_response(raw_msg))
                    self.dialog.append({"role": "user", "content": length_continuation_user_text()})
                    cont_i += 1
                    continue

                yield {"type": "status", "phase": "answer", "detail": "模型返回最终回答"}
                graph_finish_final(iteration=iteration, outcome="final")
                yield {
                    "type": "final",
                    "content": out or "No response.",
                    "chunked": bool(streamed_parts),
                }
                self.done = True
                return

            self.dialog.append(assistant_turn_from_response(raw_msg))
            self.pending_tool_calls = tool_calls
            self.pending_executor = executor

        except Exception as e:
            from ly_next.agent.react.helpers import format_agent_error

            logger.warning(
                "[agent.native] chat_with_tools failed: %s",
                format_agent_error(e),
            )
            raise

        names = [tc["name"] for tc in tool_calls]
        graph_begin_tool_phase(iteration=iteration, tool_names=names)
        yield {
            "type": "status",
            "phase": "tools",
            "iteration": iteration,
            "detail": f"模型发起 {len(tool_calls)} 次函数调用: {', '.join(names)}",
            "tool_names": names,
        }

    async def step_tools(self) -> AsyncIterator[dict[str, Any]]:
        deps = self.deps
        iteration = self.iteration
        tool_calls = self.pending_tool_calls
        executor = self.pending_executor
        self.pending_tool_calls = []
        self.pending_executor = None

        if not tool_calls:
            return

        if executor is not None:
            for start_ev in executor.dispatch_from_completion(tool_calls):
                yield start_ev
            if executor.has_pending:
                async for tool_ev in executor.iter_results():
                    if tool_ev.get("type") == "_tool_outcome":
                        outcome = tool_ev["outcome"]
                    else:
                        yield tool_ev
                        continue

                    final = await self._apply_tool_outcome(outcome, iteration)
                    if final is not None:
                        yield final
                        return
                graph_end_tool_phase(iteration=iteration)
                self.iteration += 1
                return

        planned: list[dict[str, Any]] = []
        for idx, tc in enumerate(tool_calls):
            name = tc["name"]
            raw_args = tc.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            if aborted(deps):
                yield {"type": "final", "content": "（对话已由用户中断）"}
                self.done = True
                return

            tcid = tc.get("id") or f"call_{iteration}_{idx}_{name}"
            yield {
                "type": "tool_start",
                "tool": name,
                "call_id": str(tcid),
                "iteration": iteration,
                "args_preview": preview_json(args, limit=1200),
            }
            planned.append({"name": name, "args": args, "call_id": str(tcid)})

        if len(planned) == 1:
            item = planned[0]
            outcomes = [
                await execute_native_tool_call(
                    deps,
                    name=item["name"],
                    args=item["args"],
                    call_id=item["call_id"],
                    run_tag=self.run_tag,
                    allowed_set=self.allowed_set,
                )
            ]
        else:
            outcomes = await asyncio.gather(
                *[
                    execute_native_tool_call(
                        deps,
                        name=item["name"],
                        args=item["args"],
                        call_id=item["call_id"],
                        run_tag=self.run_tag,
                        allowed_set=self.allowed_set,
                    )
                    for item in planned
                ]
            )

        for _item, outcome in zip(planned, outcomes, strict=True):
            name = outcome["name"]
            yield {
                "type": "tool_done",
                "tool": name,
                "call_id": outcome["call_id"],
                "iteration": iteration,
                "success": outcome["ok"],
                "result_preview": outcome["preview"],
            }
            final = await self._apply_tool_outcome(outcome, iteration)
            if final is not None:
                yield final
                return

        graph_end_tool_phase(iteration=iteration)
        self.iteration += 1

    async def _apply_tool_outcome(
        self, outcome: dict[str, Any], iteration: int
    ) -> dict[str, Any] | None:
        """Apply tool outcome; return final event if session should stop."""
        sig = outcome["sig"]
        self.same_sig_count = self.same_sig_count + 1 if sig == self.last_sig else 1
        self.last_sig = sig

        if not outcome["ok"]:
            self.fail_streak += 1
        else:
            self.fail_streak = 0

        deps = self.deps
        if self.same_sig_count >= deps.loop_max_repeat_same_tool:
            graph_finish_final(iteration=iteration, outcome="repeat_tool")
            self.done = True
            return {"type": "final", "content": "Stopped: repeated identical tool calls."}
        if self.fail_streak >= deps.loop_max_consecutive_tool_failures:
            graph_finish_final(iteration=iteration, outcome="tool_failures")
            self.done = True
            return {
                "type": "final",
                "content": "Stopped: too many consecutive tool failures.",
            }

        self.dialog.append(
            {
                "role": "tool",
                "tool_call_id": outcome["call_id"],
                "content": outcome["tool_body"],
            }
        )
        return None

    async def iter_loop(self) -> AsyncIterator[dict[str, Any]]:
        if self.direct_only:
            async for ev in self.iter_direct_answer():
                yield ev
            return

        while not self.done and self.iteration < self.deps.max_steps:
            async for ev in self.step_llm():
                yield ev
            if self.done:
                break
            if self.pending_tool_calls:
                async for ev in self.step_tools():
                    yield ev
            if self.done:
                break

        if not self.done:
            graph_finish_final(iteration=max(0, self.deps.max_steps - 1), outcome="max_steps")
            yield {"type": "final", "content": "Maximum steps reached."}
            self.done = True


async def iter_native_react_via_session(
    messages: list[dict[str, Any]], deps: AgentDeps
) -> AsyncIterator[dict[str, Any]]:
    if not deps.tool_registry:
        raise RuntimeError("no tool registry")
    session = NativeReactSession.from_messages(messages, deps)
    async for ev in session.iter_loop():
        yield ev
