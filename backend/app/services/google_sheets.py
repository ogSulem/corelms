from __future__ import annotations

import json
import logging
from functools import lru_cache

from google.oauth2 import service_account
from googleapiclient.discovery import build


log = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


@lru_cache(maxsize=8)
def _cached_client(*, creds_json: str, api_key: str):
    cj = str(creds_json or "").strip()
    ak = str(api_key or "").strip()

    if cj:
        info = json.loads(cj)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    if ak:
        # Public sheets access via API key (no OAuth)
        return build("sheets", "v4", developerKey=ak, cache_discovery=False)

    raise ValueError("Google Sheets client requires either creds_json or api_key")


def read_values(*, spreadsheet_id: str, range_a1: str, creds_json: str | None = None, api_key: str | None = None) -> list[list[str]]:
    """Read a values range from Google Sheets.

    Returns list of rows, each row is list of cell strings.
    """

    sid = str(spreadsheet_id or "").strip()
    if not sid:
        return []
    r = str(range_a1 or "").strip()
    if not r:
        return []

    svc = _cached_client(creds_json=str(creds_json or "").strip(), api_key=str(api_key or "").strip())
    resp = svc.spreadsheets().values().get(spreadsheetId=sid, range=r).execute()
    values = resp.get("values") or []
    out: list[list[str]] = []
    for row in values:
        if not isinstance(row, list):
            continue
        out.append([str(x) if x is not None else "" for x in row])
    return out


def list_sheet_titles(*, spreadsheet_id: str, creds_json: str | None = None, api_key: str | None = None) -> list[str]:
    """Return sheet/tab titles in the order they appear in the spreadsheet UI."""

    sid = str(spreadsheet_id or "").strip()
    if not sid:
        return []

    svc = _cached_client(creds_json=str(creds_json or "").strip(), api_key=str(api_key or "").strip())
    resp = (
        svc.spreadsheets()
        .get(
            spreadsheetId=sid,
            fields="sheets(properties(title,index))",
        )
        .execute()
    )

    sheets = resp.get("sheets") if isinstance(resp, dict) else None
    out: list[tuple[int, str]] = []
    for sh in sheets or []:
        try:
            props = (sh or {}).get("properties") if isinstance(sh, dict) else None
            if not isinstance(props, dict):
                continue
            title = str(props.get("title") or "").strip()
            idx = int(props.get("index") or 0)
            if title:
                out.append((idx, title))
        except Exception:
            continue

    out.sort(key=lambda x: int(x[0]))
    return [t for _, t in out]
