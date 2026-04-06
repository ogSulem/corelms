from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.core.config import settings
from app.core.redis_client import get_redis
from app.services.google_sheets import list_sheet_titles, read_values


log = logging.getLogger(__name__)


@dataclass
class LinkItem:
    name: str
    link: str


@dataclass
class VideoItem:
    tab: str
    name: str
    link: str


def _normalize(s: str) -> str:
    return str(s or "").strip()


def _parse_simple_sheet(rows: list[list[str]]) -> list[LinkItem]:
    # Expect header: name | link
    out: list[LinkItem] = []
    for idx, row in enumerate(rows or []):
        if idx == 0:
            continue
        name = _normalize(row[0] if len(row) > 0 else "")
        link = _normalize(row[1] if len(row) > 1 else "")
        if not name or not link:
            continue
        out.append(LinkItem(name=name, link=link))
    return out


def _parse_videos_sheet(rows: list[list[str]]) -> list[VideoItem]:
    # Expect header: tab | name | link
    out: list[VideoItem] = []
    for idx, row in enumerate(rows or []):
        if idx == 0:
            continue
        tab = _normalize(row[0] if len(row) > 0 else "")
        name = _normalize(row[1] if len(row) > 1 else "")
        link = _normalize(row[2] if len(row) > 2 else "")
        if not tab or not name or not link:
            continue
        out.append(VideoItem(tab=tab, name=name, link=link))
    return out


def get_sales_links_payload(*, bypass_cache: bool = False) -> dict[str, object]:
    sid = str(settings.sales_links_spreadsheet_id or "").strip()
    creds = str(settings.sales_links_service_account_json or "").strip()
    api_key = str(settings.sales_links_google_api_key or "").strip()
    if not sid or (not creds and not api_key):
        return {"blocks": []}

    cache_key = f"sales:links:v2:{sid}"
    if not bypass_cache:
        try:
            r = get_redis()
            cached = r.get(cache_key)
            if cached:
                obj = json.loads(str(cached))
                if isinstance(obj, dict):
                    return obj
        except Exception:
            log.debug("get_sales_links_payload: cache read failed", exc_info=True)

    try:
        titles = list_sheet_titles(spreadsheet_id=sid, creds_json=creds or None, api_key=api_key or None)
    except Exception:
        log.warning("get_sales_links_payload: failed to read google sheets", exc_info=True)

        return {"blocks": []}

    blocks: list[dict[str, object]] = []
    for title in titles:
        try:
            rows = read_values(spreadsheet_id=sid, range_a1=f"'{title}'!A:Z", creds_json=creds or None, api_key=api_key or None)
        except Exception:
            continue
        if not rows:
            continue

        header = [str(x or "").strip().lower() for x in (rows[0] or [])]
        header = [h for h in header if h]
        if not header:
            continue

        # infer kind
        kind = "links"
        if len(header) >= 3 and header[0] == "tab" and header[1] == "name" and header[2] == "link":
            kind = "video"
        elif len(header) >= 2 and header[0] == "name" and header[1] == "link":
            kind = "links"
        else:
            # unknown sheet format - skip
            continue

        if kind == "links":
            items = _parse_simple_sheet(rows)
            blocks.append(
                {
                    "id": str(title),
                    "title": str(title),
                    "kind": "links",
                    "links": [{"title": x.name, "url": x.link} for x in items],
                }
            )
        else:
            vids = _parse_videos_sheet(rows)
            tabs: list[dict[str, object]] = []
            by_tab: dict[str, dict[str, object]] = {}
            for v in vids:
                if v.tab not in by_tab:
                    obj: dict[str, object] = {"id": v.tab, "label": v.tab, "links": []}
                    by_tab[v.tab] = obj
                    tabs.append(obj)
                try:
                    (by_tab[v.tab]["links"] or []).append({"title": v.name, "url": v.link})
                except Exception:
                    by_tab[v.tab]["links"] = [{"title": v.name, "url": v.link}]

            blocks.append(
                {
                    "id": str(title),
                    "title": str(title),
                    "kind": "video",
                    "tabs": tabs,
                }
            )

    payload: dict[str, object] = {"blocks": blocks}

    try:
        r = get_redis()
        r.setex(cache_key, 180, json.dumps(payload, ensure_ascii=False))
    except Exception:
        log.debug("get_sales_links_payload: cache write failed", exc_info=True)

    return payload
