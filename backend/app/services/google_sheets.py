"""Bounded Sheets reads. Each call owns its transport (httplib2 is not thread safe)."""
from __future__ import annotations

import json
from contextlib import contextmanager

import httplib2
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
MAX_SHEETS = 30
MAX_ROWS = 1001


@contextmanager
def sheets_client(*, creds_json: str | None = None, api_key: str | None = None):
    transport = httplib2.Http(timeout=8)
    if creds_json:
        credentials = service_account.Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        transport = AuthorizedHttp(credentials, http=transport)
    elif not api_key:
        raise ValueError("Google Sheets credentials are not configured")
    service = build("sheets", "v4", http=transport, developerKey=api_key or None, cache_discovery=False, static_discovery=True)
    try:
        yield service
    finally:
        service.close()


def _titles(service, spreadsheet_id: str) -> list[str]:
    response = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title,index))").execute(num_retries=0)
    sheets = response.get("sheets") or []
    return [str(s["properties"]["title"]) for s in sorted(sheets, key=lambda s: s.get("properties", {}).get("index", 0))
            if s.get("properties", {}).get("title")]


def _rows(value) -> list[list[str]]:
    return [[str(cell)[:4000] if cell is not None else "" for cell in row[:3]]
            for row in (value or [])[:MAX_ROWS] if isinstance(row, list)]


def read_sales_snapshot(*, spreadsheet_id: str, creds_json: str | None = None, api_key: str | None = None) -> dict:
    with sheets_client(creds_json=creds_json, api_key=api_key) as service:
        all_titles = _titles(service, spreadsheet_id)
        titles = all_titles[:MAX_SHEETS]
        if not titles:
            return {"sheets": [], "truncated": False}
        ranges = ["'" + title.replace("'", "''") + f"'!A1:C{MAX_ROWS}" for title in titles]
        # CellData.hyperlink retains HYPERLINK and named rich-text links; the
        # values endpoint would otherwise return only their visible labels.
        response = service.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=ranges, includeGridData=True,
            fields="sheets(properties(title),data(rowData(values(formattedValue,hyperlink))))").execute(num_retries=0)
        by_title = {str(sheet.get("properties", {}).get("title")): sheet for sheet in response.get("sheets", [])}
        if any(title not in by_title for title in titles):
            raise ValueError("Incomplete Sheets snapshot")
        values = []
        truncated = len(all_titles) > MAX_SHEETS
        for title in titles:
            grids = by_title[title].get("data") or []
            cells = grids[0].get("rowData", []) if grids else []
            truncated = truncated or len(cells) >= MAX_ROWS
            header = [str(cell.get("formattedValue") or "").strip().lower() for cell in (cells[0].get("values", []) if cells else [])]
            link_column = next((i for i, label in enumerate(header[:3]) if label in {"link", "ссылка"}), -1)
            rows = [[(cell.get("hyperlink") if row_index > 0 and i == link_column else None) or cell.get("formattedValue", "")
                     for i, cell in enumerate(row.get("values", [])[:3])] for row_index, row in enumerate(cells[:MAX_ROWS])]
            values.append((title, _rows(rows)))
        return {"sheets": values, "truncated": truncated}


def list_sheet_titles(*, spreadsheet_id: str, creds_json: str | None = None, api_key: str | None = None) -> list[str]:
    with sheets_client(creds_json=creds_json, api_key=api_key) as service:
        return _titles(service, spreadsheet_id)[:MAX_SHEETS]


def read_values(*, spreadsheet_id: str, range_a1: str, creds_json: str | None = None, api_key: str | None = None) -> list[list[str]]:
    with sheets_client(creds_json=creds_json, api_key=api_key) as service:
        response = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_a1).execute(num_retries=0)
        return _rows(response.get("values"))
