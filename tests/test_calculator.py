import pytest

from app.tools.calculator import CalculatorError, calculate


@pytest.mark.parametrize("expression, expected", [
    ("2 + 3 * 4", 14),
    ("(1520000 - 1340000) / 1340000 * 100", pytest.approx(13.432835820895)),
    ("1250000000 * 0.015", 18750000),
    ("2^10", 1024),  # caret is accepted as power
    ("-5 + abs(-3)", -2),
    ("round(2 / 3, 4)", 0.6667),
    ("max(3, 9, 4) - min(3, 9, 4)", 6),
    ("sqrt(144)", 12),
    ("0.1 + 0.2", 0.3),  # float noise is cleaned up
])
def test_valid_expressions(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo hacked')",  # code execution attempt
    "open('/etc/passwd').read()",
    "x + 1",  # unknown name
    "(1).__class__",  # attribute access
    "'abc' * 3",  # strings
    "True + 1",  # booleans are not numbers here
    "lambda: 1",
    "",
])
def test_rejects_anything_that_is_not_arithmetic(expression):
    with pytest.raises(CalculatorError):
        calculate(expression)


def test_division_by_zero_is_a_clear_error():
    with pytest.raises(CalculatorError, match="Division by zero"):
        calculate("10 / (5 - 5)")


def test_huge_exponent_is_refused():
    with pytest.raises(CalculatorError, match="Exponent"):
        calculate("9 ** 9 ** 9")


def test_overlong_expression_is_refused():
    with pytest.raises(CalculatorError, match="longer than"):
        calculate("1+" * 200 + "1")
