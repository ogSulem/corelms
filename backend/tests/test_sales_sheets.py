from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import threading
from types import SimpleNamespace

import pytest

from app.services import google_sheets, sales_links
from app.models.user import UserRole


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    sales_links._memory.clear(); sales_links._errors.clear()
    monkeypatch.setattr(sales_links.settings, 'sales_links_spreadsheet_id', 'sheet-id')
    monkeypatch.setattr(sales_links.settings, 'sales_links_google_api_key', 'test-key-not-a-live-secret')
    monkeypatch.setattr(sales_links.settings, 'sales_links_service_account_json', None)
    yield
    sales_links._memory.clear(); sales_links._errors.clear()


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,x', 'ftp://example.com', 'https://user:pass@example.com',
                                '//example.com/x', 'https://example.com\\bad', 'https://example.com/a b', 'https://example.com:99999', 'https://example.com/\x00'])
def test_sheet_links_never_pass_unsafe_addresses(url):
    assert sales_links.safe_link(url) is None


def snapshot():
    return {'sheets': [
        ('Документы', [['Название', 'Ссылка'], ['Каталог', 'https://example.com/catalog'], ['Небезопасно', 'javascript:alert(1)']]),
        ("Видео O'Brien", [['tab', 'name', 'link'], ['Клиент', 'Вступление', 'https://example.com/video']]),
    ], 'truncated': False}


def test_bilingual_headers_video_groups_and_invalid_rows_are_explicit():
    blocks, warnings = sales_links.parse_snapshot(snapshot())
    assert len(blocks) == 2 and len(blocks[0]['links']) == 1 and blocks[1]['tabs'][0]['label'] == 'Клиент'
    assert len(warnings) == 1 and '1' in warnings[0]
    assert sales_links.safe_link('https://пример.рф/каталог')


def test_cache_keeps_last_good_on_failure_with_backoff_and_manual_recovery(monkeypatch, redis_memory):
    calls = []
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', lambda **kw: calls.append(1) or snapshot())
    good = sales_links.get_sales_links_payload()
    assert good['status'] == 'fresh' and len(calls) == 1
    assert sales_links.get_sales_links_payload() == good and len(calls) == 1
    def fail(**kw): calls.append(1); raise TimeoutError('URL WITH SECRET MUST NOT BE EXPOSED')
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', fail)
    failed = sales_links.get_sales_links_payload(bypass_cache=True)
    assert failed['status'] == 'stale' and failed['blocks'] == good['blocks'] and failed['last_success_at'] == good['last_success_at']
    assert 'SECRET' not in json.dumps(failed)
    assert sales_links.get_sales_links_payload()['status'] == 'stale' and len(calls) == 2
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', lambda **kw: {'sheets': [('Новый', [['name', 'link'], ['Новая', 'https://example.com/new']])], 'truncated': False})
    recovered = sales_links.get_sales_links_payload(bypass_cache=True)
    assert recovered['status'] == 'fresh' and recovered['blocks'][0]['title'] == 'Новый'


def test_redis_outage_uses_bounded_memory_fallback_and_failure_backoff(monkeypatch):
    def offline(): raise ConnectionError('redis offline')
    monkeypatch.setattr(sales_links, 'get_redis', offline)
    calls = []
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', lambda **kw: calls.append(1) or snapshot())
    good = sales_links.get_sales_links_payload()
    assert sales_links.get_sales_links_payload() == good and len(calls) == 1
    def fail(**kw): calls.append(1); raise TimeoutError()
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', fail)
    assert sales_links.get_sales_links_payload(bypass_cache=True)['status'] == 'stale'
    assert sales_links.get_sales_links_payload()['status'] == 'stale' and len(calls) == 2
    key = 'sales:links:v3:sheet-id'
    old = {**good, 'last_success_at': (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}
    sales_links._memory[key] = old, 0; sales_links._errors.clear()
    assert sales_links.get_sales_links_payload()['status'] == 'error'


def test_singleflight_never_blocks_second_request_or_replaces_good_data(monkeypatch):
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', lambda **kw: snapshot())
    good = sales_links.get_sales_links_payload()
    entered, release = threading.Event(), threading.Event()
    def slow(**kw):
        entered.set(); assert release.wait(3); return snapshot()
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', slow)
    result = []
    thread = threading.Thread(target=lambda: result.append(sales_links.get_sales_links_payload(bypass_cache=True)))
    thread.start()
    try:
        assert entered.wait(2)
        busy = sales_links.get_sales_links_payload(bypass_cache=True)
        assert busy['refreshing'] and busy['blocks'] == good['blocks']
    finally:
        release.set(); thread.join(4)
    assert result[0]['status'] == 'fresh'


def test_unlock_connection_failure_is_not_a_public_500(monkeypatch):
    # Local single-flight is still needed when another API process owned the Redis lock.
    sales_links._refresh_lock.acquire()
    monkeypatch.setattr(sales_links, 'release_job_lock', lambda *args: (_ for _ in ()).throw(ConnectionError()))
    try:
        result = sales_links.get_sales_links_payload(bypass_cache=True)
        assert result['refreshing'] and result['status'] == 'loading'
    finally:
        sales_links._refresh_lock.release()


def test_only_superadmin_forces_refresh_or_receives_edit_url(client, make_user, monkeypatch):
    monkeypatch.setattr(sales_links, 'read_sales_snapshot', lambda **kw: snapshot())
    _, employee = make_user(); _, admin = make_user(UserRole.admin); _, root = make_user(UserRole.superadmin)
    for headers in (employee, admin):
        assert client.get('/sales-links?bypass_cache=true', headers=headers).status_code == 403
        assert client.get('/sales-links', headers=headers).json()['source_url'] is None
    data = client.get('/sales-links?bypass_cache=true', headers=root).json()
    assert data['source_url'] == 'https://docs.google.com/spreadsheets/d/sheet-id/edit' and data['blocks']


def test_transport_is_private_per_call_ranges_are_escaped_and_reads_bounded(monkeypatch):
    records, closed = [], []
    class Service:
        def spreadsheets(self): return self
        def values(self): return self
        def get(self, **kwargs):
            if 'ranges' not in kwargs:
                return SimpleNamespace(execute=lambda **kw: {'sheets': [{'properties': {'title': "O'Brien", 'index': 0}}]})
            records.append(kwargs)
            cells = [{'formattedValue': value} for value in ['x' * 5000, 'b', 'c', 'd']]
            return SimpleNamespace(execute=lambda **kw: {'sheets': [{'properties': {'title': "O'Brien"}, 'data': [{'rowData': [{'values': cells}] * 1002}]}]})
        def close(self): closed.append(self)
    transports = []
    monkeypatch.setattr(google_sheets.httplib2, 'Http', lambda **kwargs: transports.append(kwargs) or object())
    monkeypatch.setattr(google_sheets, 'build', lambda *args, **kwargs: Service())
    for _ in range(2):
        data = google_sheets.read_sales_snapshot(spreadsheet_id='id', api_key='not-real')
        assert data['truncated'] and len(data['sheets'][0][1]) == 1001 and len(data['sheets'][0][1][0]) == 3
        assert len(data['sheets'][0][1][0][0]) == 4000
    assert records[0]['ranges'] == ["'O''Brien'!A1:C1001"] and len(closed) == 2 and transports == [{'timeout': 8}, {'timeout': 8}]


def test_partial_batch_is_not_treated_as_a_success(monkeypatch):
    class Service:
        def spreadsheets(self): return self
        def values(self): return self
        def get(self, **kwargs):
            if 'ranges' in kwargs:
                return SimpleNamespace(execute=lambda **kw: {'sheets': [{'properties': {'title': 'A'}, 'data': []}]})
            return SimpleNamespace(execute=lambda **kw: {'sheets': [{'properties': {'title': title}} for title in ['A', 'B']]})
    @contextmanager
    def client(**kw): yield Service()
    monkeypatch.setattr(google_sheets, 'sheets_client', client)
    with pytest.raises(ValueError, match='Incomplete'):
        google_sheets.read_sales_snapshot(spreadsheet_id='id', api_key='x')


def test_named_hyperlinks_keep_the_target_without_replacing_the_title(monkeypatch):
    class Service:
        def spreadsheets(self): return self
        def get(self, **kwargs):
            data = {'properties': {'title': 'Links'}}
            if 'ranges' in kwargs:
                data['data'] = [{'rowData': [
                    {'values': [{'formattedValue': 'name'}, {'formattedValue': 'link'}]},
                    {'values': [{'formattedValue': 'Каталог', 'hyperlink': 'https://example.com/title'},
                                {'formattedValue': 'Открыть документ', 'hyperlink': 'https://example.com/catalog'}]},
                ]}]
            return SimpleNamespace(execute=lambda **kw: {'sheets': [data]})
    @contextmanager
    def client(**kw): yield Service()
    monkeypatch.setattr(google_sheets, 'sheets_client', client)
    snapshot = google_sheets.read_sales_snapshot(spreadsheet_id='id', api_key='x')
    blocks, warnings = sales_links.parse_snapshot(snapshot)
    assert not warnings and blocks[0]['links'] == [{'title': 'Каталог', 'url': 'https://example.com/catalog'}]
