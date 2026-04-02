from __future__ import annotations

import argparse
import os
import pathlib
import sys
from dataclasses import dataclass, field

from sqlalchemy import select

# Ensure imports work when running from any CWD (Windows / local) and in Docker (/app)
_HERE = pathlib.Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, "/app")
sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap


@dataclass
class Node:
    # Tree node.
    children: dict[str, "Node"] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)


def _normalize_path(s: str) -> list[str]:
    raw = str(s or "").strip().replace("\\", "/")
    raw = raw.lstrip("/")
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    return parts


def _outline_parts(s: Submodule) -> list[str]:
    try:
        p = str(getattr(s, "outline_path", "") or "").strip().replace("\\", "/")
    except Exception:
        p = ""
    if not p:
        return []
    return [seg.strip() for seg in p.split("/") if seg.strip()]


def _insert_path(root: Node, parts: list[str]) -> None:
    if not parts:
        return
    if len(parts) == 1:
        root.files.append(parts[0])
        return
    cur = root
    for seg in parts[:-1]:
        cur = cur.children.setdefault(seg, Node())
    cur.files.append(parts[-1])


def _render_tree(node: Node, indent: str = "") -> list[str]:
    lines: list[str] = []

    for dname in sorted(node.children.keys(), key=lambda x: x.lower()):
        lines.append(f"{indent}- {dname}/")
        lines.extend(_render_tree(node.children[dname], indent=indent + "  "))

    for fname in sorted(node.files, key=lambda x: x.lower()):
        lines.append(f"{indent}- {fname}")

    return lines


def _render_tree_as_sections(node: Node) -> list[str]:
    lines: list[str] = []

    for dname in sorted(node.children.keys(), key=lambda x: x.lower()):
        lines.append(f"## {dname}/")
        child = node.children[dname]
        rendered = _render_tree(child, indent="")
        lines.extend(rendered if rendered else ["- (пусто)"])
        lines.append("")

    for fname in sorted(node.files, key=lambda x: x.lower()):
        lines.append(f"## {fname}")
        lines.append("")

    return lines


def export_modules_tree(*, out_path: str, include_module_assets: bool) -> int:
    out: list[str] = []

    with SessionLocal() as db:
        modules = db.scalars(select(Module).order_by(Module.title)).all()

        for mi, m in enumerate(modules, start=1):
            out.append(f"# {m.title} ({m.id})")
            out.append("")

            module_tree = Node()

            subs = db.scalars(select(Submodule).where(Submodule.module_id == m.id)).all()
            for s in subs:
                prefix_parts: list[str] = []
                try:
                    prefix_parts.extend(_outline_parts(s))
                except Exception:
                    prefix_parts = []

                is_folder = bool(getattr(s, "is_folder", False))
                if is_folder:
                    folder_title = str(getattr(s, "title", "") or "").strip() or "Папка"
                    prefix_parts.append(folder_title)

                rows = db.execute(
                    select(SubmoduleAssetMap.order, ContentAsset)
                    .join(ContentAsset, ContentAsset.id == SubmoduleAssetMap.asset_id)
                    .where(SubmoduleAssetMap.submodule_id == s.id)
                    .order_by(SubmoduleAssetMap.order)
                ).all()
                for _, a in rows:
                    parts = _normalize_path(getattr(a, "original_filename", "") or "")
                    if not parts:
                        parts = [str(getattr(a, "object_key", "") or "") or str(getattr(a, "id", ""))]
                    _insert_path(module_tree, list(prefix_parts) + parts)

            if include_module_assets:
                try:
                    pfx = str(getattr(m, "storage_prefix", "") or "").strip() or f"modules/{m.id}/"
                    if pfx and (not pfx.endswith("/")):
                        pfx = pfx + "/"
                    prefix = f"{pfx}_module/"

                    mod_assets = db.scalars(
                        select(ContentAsset)
                        .where(ContentAsset.object_key.like(prefix + "%"))
                        .order_by(ContentAsset.original_filename)
                    ).all()

                    for a in mod_assets:
                        parts = _normalize_path(getattr(a, "original_filename", "") or "")
                        if not parts:
                            parts = [str(getattr(a, "object_key", "") or "") or str(getattr(a, "id", ""))]
                        _insert_path(module_tree, ["_module"] + parts)
                except Exception:
                    pass

            if not module_tree.children and not module_tree.files:
                out.append("(нет файлов)")
                out.append("")
            else:
                out.extend(_render_tree_as_sections(module_tree))

            if mi != len(modules):
                out.append("---")
                out.append("")

    pathlib.Path(out_path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Export imported modules tree (folders/files) into a Markdown document.")
    ap.add_argument("--out", default="modules_tree.md", help="Output markdown path")
    ap.add_argument(
        "--include-module-assets",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include module-level assets stored under storage_prefix/_module/ (default: true)",
    )
    args = ap.parse_args()

    out_path = str(args.out or "modules_tree.md")
    return export_modules_tree(out_path=out_path, include_module_assets=bool(args.include_module_assets))


if __name__ == "__main__":
    raise SystemExit(main())
