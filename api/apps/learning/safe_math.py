"""Whitelist validator for visualization formulas. The browser evaluates them
with its own tiny parser; nothing is ever passed to eval()."""

import ast

ALLOWED_FUNCS = {"sin", "cos", "exp", "log", "sqrt", "abs"}
_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Call,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)


def valid_expression(expr: str, variables: set[str]) -> bool:
    if not expr or len(expr) > 120:
        return False
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, _NODES):
            return False
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            return False
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS or len(node.args) != 1
        ):
            return False
        if isinstance(node, ast.Name) and node.id not in variables | ALLOWED_FUNCS:
            return False
    return True
