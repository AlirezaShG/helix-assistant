"""Calculator tool: exact arithmetic for the coordinator."""

import ast
import math
import operator

MAX_EXPRESSION_LENGTH = 300
MAX_EXPONENT = 100

BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPERATORS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCTIONS = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt}


class CalculatorError(ValueError):
    pass


def calculate(expression: str) -> int | float:
    expression = expression.strip()
    if not expression:
        raise CalculatorError("The expression is empty.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError(f"The expression is longer than {MAX_EXPRESSION_LENGTH} characters.")

    # Accept the symbols people (and LLMs) commonly write.
    expression = expression.replace("^", "**").replace("×", "*").replace("÷", "/")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"Not a valid arithmetic expression: {expression!r}") from exc

    try:
        result = _evaluate(tree.body)
    except ZeroDivisionError as exc:
        raise CalculatorError("Division by zero.") from exc
    except (OverflowError, ValueError, TypeError) as exc:  # e.g. sqrt(-1), float overflow, min()
        raise CalculatorError(f"Cannot compute this: {exc}") from exc

    if isinstance(result, float):
        result = round(result, 10)
        if result.is_integer():
            result = int(result)
    return result


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):  # bool is excluded on purpose
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError(f"Exponents above {MAX_EXPONENT} are not allowed.")
        return BINARY_OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
        return UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))

    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS and not node.keywords):
        return FUNCTIONS[node.func.id](*[_evaluate(arg) for arg in node.args])

    raise CalculatorError(f"Unsupported element in expression: {ast.unparse(node)!r}")
