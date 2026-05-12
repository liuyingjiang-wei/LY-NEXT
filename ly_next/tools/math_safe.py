"""Strict subset of arithmetic for calculator tool (no eval)."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

_MAX_EXPR_CHARS = 512
_MAX_AST_NODES = 120

_ALLOWED_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
}

_ALLOWED_NAMES: dict[str, float] = {"pi": math.pi, "e": math.e}

_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_UNARY: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _count_nodes(node: ast.AST) -> int:
    n = 0
    for child in ast.iter_child_nodes(node):
        n += _count_nodes(child)
    return n + 1


def eval_math_expression(expression: str) -> float | int:
    s = (expression or "").strip()
    if not s:
        raise ValueError("Empty expression")
    if len(s) > _MAX_EXPR_CHARS:
        raise ValueError("Expression too long")

    tree = ast.parse(s, mode="eval")
    if not isinstance(tree, ast.Expression):
        raise ValueError("Invalid parse root")
    if _count_nodes(tree) > _MAX_AST_NODES:
        raise ValueError("Expression too complex")

    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            raise ValueError("Booleans not allowed")
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Only numeric constants allowed")

    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise ValueError("Operator not allowed")
        op_fn = _BINOPS[type(node.op)]
        return op_fn(_eval_node(node.left), _eval_node(node.right))

    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY:
            raise ValueError("Unary operator not allowed")
        return _UNARY[type(node.op)](_eval_node(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls allowed")
        name = node.func.id
        if name not in _ALLOWED_FUNCS:
            raise ValueError(f"Function not allowed: {name}")
        if node.keywords:
            raise ValueError("Keyword arguments not allowed")
        fn = _ALLOWED_FUNCS[name]
        args = [_eval_node(a) for a in node.args]
        return fn(*args)

    if isinstance(node, ast.Name):
        if node.id not in _ALLOWED_NAMES:
            raise ValueError(f"Name not allowed: {node.id}")
        return _ALLOWED_NAMES[node.id]

    if isinstance(node, ast.List):
        return [_eval_node(elt) for elt in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(elt) for elt in node.elts)

    raise ValueError(f"Syntax not allowed: {type(node).__name__}")
