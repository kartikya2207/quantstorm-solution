"""Write SUBSTITUTE-bid variants of the shipped bot, BOM-free."""
import io

src = io.open("FINAL_SUBMISSION.py", encoding="utf-8").read()
for tag, val, nm in (("X2_sub18", 18, "KV6X2"), ("X3_sub23", 23, "KV6X3")):
    out = src.replace("SUBSTITUTE_BID = 13", "SUBSTITUTE_BID = %d" % val)
    out = out.replace('name = "KV6X1"', 'name = "%s"' % nm)
    assert "SUBSTITUTE_BID = %d" % val in out and nm in out
    io.open(tag + ".py", "w", encoding="utf-8", newline="").write(out)
    print(tag, "written BOM-free, bid =", val)
