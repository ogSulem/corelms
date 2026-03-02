import re
from pathlib import Path

p = Path(__file__).resolve().parent / "frontend" / "src" / "app" / "adminpanel" / "_components" / "ImportTab.tsx"
text = p.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()

# Strip strings/template literals crudely to avoid false positives.
def strip_strings(s: str) -> str:
    s = re.sub(r"`[^`]*`", "``", s)
    s = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', s)
    s = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", s)
    return s

stack: list[int] = []

for ln, raw in enumerate(lines, 1):
    s = strip_strings(raw)
    for m in re.finditer(r"</div>|<div(?=\s|>)", s):
        tok = m.group(0)
        if tok.startswith("</div"):
            if stack:
                stack.pop()
            else:
                print(f"EXTRA_CLOSE </div> at line {ln}")
        else:
            stack.append(ln)

print(f"UNCLOSED <div> count: {len(stack)}")
print("UNCLOSED lines (tail):", stack[-30:])

for ln in stack[-10:]:
    lo = max(1, ln - 2)
    hi = min(len(lines), ln + 2)
    print("\n--- around", ln)
    for k in range(lo, hi + 1):
        print(f"{k}: {lines[k-1]}")
