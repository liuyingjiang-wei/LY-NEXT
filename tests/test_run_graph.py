from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from ly_next.api import runs_api
from ly_next.core.run_graph import (
    GRAPH_EDGE,
    GRAPH_NODE_ENTER,
    GRAPH_NODE_EXIT,
    NODE_EXECUTE_TOOLS,
    NODE_FINALIZE,
    NODE_PREP,
    NODE_REACT_STEP,
    build_run_graph,
    emit_graph_edge,
    emit_graph_node_enter,
    emit_graph_node_exit,
)
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.run_store import clear_memory_runs_for_tests, get_run_store
from ly_next.core.run_telemetry import set_run_loop_kind


@pytest.fixture(autouse=True)
def _clear_runs():
    clear_memory_runs_for_tests()
    yield
    clear_memory_runs_for_tests()


def test_build_run_graph_from_native_events():
    events = [
        {"seq": 1, "kind": GRAPH_NODE_ENTER, "payload": {"node": NODE_PREP}},
        {"seq": 2, "kind": GRAPH_NODE_EXIT, "payload": {"node": NODE_PREP, "outcome": "ready"}},
        {
            "seq": 3,
            "kind": GRAPH_EDGE,
            "payload": {"from": NODE_PREP, "to": NODE_REACT_STEP},
        },
        {
            "seq": 4,
            "kind": GRAPH_NODE_ENTER,
            "payload": {"node": NODE_REACT_STEP, "iteration": 0},
        },
        {
            "seq": 5,
            "kind": GRAPH_NODE_EXIT,
            "payload": {"node": NODE_REACT_STEP, "iteration": 0, "outcome": "tool_calls"},
        },
        {
            "seq": 6,
            "kind": GRAPH_EDGE,
            "payload": {
                "from": NODE_REACT_STEP,
                "to": NODE_EXECUTE_TOOLS,
                "iteration": 0,
                "tools": ["web_search"],
            },
        },
        {
            "seq": 7,
            "kind": "tool_start",
            "payload": {"tool": "web_search", "iteration": 0},
        },
        {
            "seq": 8,
            "kind": GRAPH_NODE_EXIT,
            "payload": {"node": NODE_EXECUTE_TOOLS, "iteration": 0, "outcome": "ok"},
        },
        {
            "seq": 9,
            "kind": GRAPH_EDGE,
            "payload": {"from": NODE_EXECUTE_TOOLS, "to": NODE_REACT_STEP, "iteration": 1},
        },
        {
            "seq": 10,
            "kind": GRAPH_NODE_EXIT,
            "payload": {"node": NODE_REACT_STEP, "iteration": 1, "outcome": "final"},
        },
        {
            "seq": 11,
            "kind": GRAPH_EDGE,
            "payload": {"from": NODE_REACT_STEP, "to": NODE_FINALIZE, "iteration": 1},
        },
    ]

    graph = build_run_graph("run-1", events, loop_kind="native", mode="react")

    assert graph["graph_schema"]["id"] == "native_react"
    assert len(graph["executed_path"]) >= 8
    assert graph["stats"]["react_iterations"] == 2
    assert "react_step" in graph["mermaid"]
    assert graph["timeline"][0]["node"] == NODE_PREP


@pytest.mark.asyncio
async def test_runs_api_graph_endpoint():
    run_id = str(uuid.uuid4())
    token = await start_observed_run(run_id, mode="react", thread_id="t1")
    set_run_loop_kind("native")
    emit_graph_node_enter(NODE_PREP)
    emit_graph_node_exit(NODE_PREP, outcome="ready")
    emit_graph_edge(NODE_PREP, NODE_REACT_STEP)
    emit_graph_node_enter(NODE_REACT_STEP, iteration=0)
    emit_graph_node_exit(NODE_REACT_STEP, iteration=0, outcome="final")
    emit_graph_edge(NODE_REACT_STEP, NODE_FINALIZE, iteration=0)
    await finish_observed_run(token, run_id, status="ok")

    graph = await runs_api.get_run_graph(run_id)
    assert graph["run_id"] == run_id
    assert graph["loop_kind"] == "native"
    assert graph["graph_schema"]["id"] == "native_react"
    assert any(step.get("node") == NODE_REACT_STEP for step in graph["executed_path"])


@pytest.mark.asyncio
async def test_runs_api_graph_not_found():
    with pytest.raises(HTTPException) as exc:
        await runs_api.get_run_graph(str(uuid.uuid4()))
    assert exc.value.status_code == 404
