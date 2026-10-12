"""Show every AST-level difference between two bot files."""
import ast
import sys

a_path, b_path = sys.argv[1], sys.argv[2]
a = ast.parse(open(a_path, encoding="utf-8").read())
b = ast.parse(open(b_path, encoding="utf-8").read())


def nodes(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.expr) or isinstance(n, ast.stmt):
            try:
                out.append((type(n).__name__, ast.unparse(n)))
            except Exception:
                pass
    return out


na, nb = nodes(a), nodes(b)
sa, sb = set(na), set(nb)
only_a = [x for x in na if x not in sb]
only_b = [x for x in nb if x not in sa]

# Drop docstring-only differences.
only_a = [x for x in only_a if not (x[0] == "Constant" and len(x[1]) > 200)]
only_b = [x for x in only_b if not (x[0] == "Constant" and len(x[1]) > 200)]
# Drop container nodes that merely wrap the changed expression.
noise = ("Module", "FunctionDef", "ClassDef")
only_a = [x for x in only_a if x[0] not in noise]
only_b = [x for x in only_b if x[0] not in noise]

print(f"--- only in {a_path} ({len(only_a)}) ---")
for t, s in only_a:
    print(f"  [{t}] {s[:160]}")
print(f"--- only in {b_path} ({len(only_b)}) ---")
for t, s in only_b:
    print(f"  [{t}] {s[:160]}")
