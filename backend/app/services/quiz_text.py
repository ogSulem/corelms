from __future__ import annotations


def quiz_text_metrics(text: str) -> dict[str, int]:
    s = str(text or "")
    s = s.strip()
    if not s:
        return {"length": 0, "core_length": 0, "alpha": 0, "lines": 0, "non_bullet_lines": 0}

    s = s[:12000]
    lines_raw = s.splitlines()
    lines = [ln.strip() for ln in lines_raw]

    non_bullets: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("-") or ln.startswith("•") or ln.startswith("*"):
            continue
        non_bullets.append(ln)

    core = "\n".join(non_bullets).strip()
    alpha = sum(1 for ch in core if ch.isalpha())

    return {
        "length": len(s),
        "core_length": len(core),
        "alpha": int(alpha),
        "lines": int(len(lines_raw)),
        "non_bullet_lines": int(len(non_bullets)),
    }


def is_useful_quiz_text(text: str) -> bool:
    m = quiz_text_metrics(text)
    if int(m.get("core_length") or 0) < 200:
        return False
    if int(m.get("alpha") or 0) < 120:
        return False
    return True
