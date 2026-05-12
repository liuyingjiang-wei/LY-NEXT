from __future__ import annotations

import pytest

from ly_next.tools.math_safe import eval_math_expression


def test_basic_arithmetic():
    assert eval_math_expression("2 + 2") == 4
    assert eval_math_expression("3 * (4 + 5)") == 27


def test_sqrt_and_constants():
    assert eval_math_expression("sqrt(16)") == 4.0
    assert abs(eval_math_expression("sin(pi/2)") - 1.0) < 1e-9


def test_sum_list():
    assert eval_math_expression("sum([1, 2, 3])") == 6


def test_rejects_dunder_call():
    with pytest.raises(ValueError):
        eval_math_expression("__import__('os')")


def test_rejects_attribute_access():
    with pytest.raises(ValueError):
        eval_math_expression("(1).__class__")


def test_empty_rejected():
    with pytest.raises(ValueError):
        eval_math_expression("   ")
