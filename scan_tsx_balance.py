from pathlib import Path

p = Path(__file__).resolve().parent / "frontend" / "src" / "app" / "adminpanel" / "_components" / "ImportTab.tsx"
s = p.read_text(encoding="utf-8", errors="replace")

print("len", len(s))
print("backticks", s.count("`"))
print("block_open", s.count("/*"), "block_close", s.count("*/"))
print("braces", s.count("{"), s.count("}"))
print("parens", s.count("("), s.count(")"))
print("brackets", s.count("["), s.count("]"))
