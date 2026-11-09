"""Transparent task checks; these are indicators, not a universal accuracy score."""

import ast
import math
import re
import unicodedata


def python_average_correct(answer):
    match = re.search(r"```(?:python)?\s*\n(.*?)```", answer, re.S | re.I)
    source = match.group(1) if match else answer.strip()
    allowed = {
        ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If, ast.IfExp,
        ast.Compare, ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.Name, ast.Load, ast.Store,
        ast.Constant, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
        ast.Mod, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.Call, ast.Expr,
    }
    try:
        tree = ast.parse(source)
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
            return False
        function = tree.body[0]
        if function.name != "average" or function.decorator_list or function.returns:
            return False
        if [arg.arg for arg in function.args.args] != ["values"] or function.args.defaults:
            return False
        for node in ast.walk(tree):
            if type(node) not in allowed:
                return False
            if isinstance(node, ast.Name) and node.id not in {"values", "sum", "len"}:
                return False
            if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in {"sum", "len"}):
                return False
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if not math.isfinite(node.value) or abs(node.value) > 100_000:
                    return False
        # Only the tiny arithmetic/list function admitted above can execute. No
        # imports, attributes, loops, comprehensions, I/O, or general builtins.
        namespace = {"__builtins__": {}, "sum": sum, "len": len}
        exec(compile(tree, "<validated-average>", "exec"), namespace)
        average = namespace["average"]
        return average([]) is None and average([1, 2, 3]) == 2 and average([-1, 1]) == 0
    except Exception:
        return False


def check_answer(answer, checks, complete=True):
    normalized = unicodedata.normalize("NFKC", answer)
    results = []
    for check in checks:
        kind = check["kind"]
        if kind == "regex":
            passed = bool(re.search(check["pattern"], normalized, re.I | re.S))
        elif kind == "not_regex":
            passed = not re.search(check["pattern"], normalized, re.I | re.S)
        elif kind == "max_words":
            passed = len(answer.split()) <= check["value"]
        elif kind == "max_questions":
            numbered = len(re.findall(r"^\s*(?:\*\*)?\d+[.)]\s", answer, re.M))
            passed = max(answer.count("?"), numbered) <= check["value"]
        elif kind == "python_average":
            passed = python_average_correct(answer)
        else:
            raise ValueError("Unknown benchmark check: " + kind)
        results.append({"dimension": check["dimension"], "label": check["label"], "passed": bool(passed and complete and answer.strip())})
    return results
