"""Confirm FINAL_SUBMISSION.py is code-identical to H3_tight.py apart from
the module docstring, and audit randomness usage."""
import ast
import re

fin = open("FINAL_SUBMISSION.py", encoding="utf-8").read()
h3 = open("H3_tight.py", encoding="utf-8").read()

ta, tb = ast.parse(fin), ast.parse(h3)
# Drop the module docstring from each tree, then compare everything else.
for t in (ta, tb):
    if (t.body and isinstance(t.body[0], ast.Expr)
            and isinstance(t.body[0].value, ast.Constant)
            and isinstance(t.body[0].value.value, str)):
        t.body.pop(0)
print("code identical to H3_tight (docstring aside):", ast.dump(ta) == ast.dump(tb))

# Randomness audit on the submission file.
print("\n-- randomness audit --")
for i, line in enumerate(fin.splitlines(), 1):
    if "random" in line or "rng" in line:
        print(f"  {i:4d}: {line.strip()}")
bad = re.findall(r"(?<!self\.)\brandom\.(?!Random\()\w+", fin)
print("bare random.* module calls:", bad if bad else "NONE")
print("self.rng assignments:", re.findall(r"self\.rng\s*=\s*[^\n]+", fin))
