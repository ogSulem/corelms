import io
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.asset import AssetRevision, ContentAsset
from app.models.sales import SalesEntry, SalesSection
from app.models.user import UserRole
from app.services.sales_library import clean_path


@pytest.fixture()
def super_headers(make_user):
    return make_user(UserRole.superadmin)[1]


def listing(client, headers, path='', section='photos', **kwargs):
    response = client.get('/sales-files/list', headers=headers, params={"section": section, "path": path, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, headers, state, name='photo.txt', content=b'new original', replace=None):
    data = {'section': state['section'], 'path': state['path'], 'revision': str(state['revision'])}
    if replace:
        data['replace_id'] = replace
    return client.post('/sales-files/upload', headers=headers, data=data, files={'file': (name, io.BytesIO(content), 'application/octet-stream')})


@pytest.mark.parametrize('path', ['..', '../x', 'a/../b', '/a', 'a/', 'a//b', 'a\\b', 'a/./b', 'x/\x00'])
def test_sales_paths_are_rejected_not_silently_rewritten(path):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        clean_path(path)


def test_legacy_adoption_no_overwrite_no_destructive_old_endpoints(client, db, super_headers, admin_headers, make_user, storage, make_module):
    storage.objects['sales/photos/old.pdf'] = b'original document'
    state = listing(client, super_headers)
    assert len(state['entries']) == 1
    entry = state['entries'][0]
    aid = entry['asset']['asset_id']
    assert db.get(ContentAsset, uuid.UUID(aid)).object_key == 'sales/photos/old.pdf'
    assert upload(client, super_headers, state, name='old.pdf').status_code == 409
    assert client.delete('/sales-files/folder?section=photos&path=', headers=super_headers).status_code == 410
    assert client.delete('/sales-files/object?key=sales/photos/old.pdf', headers=super_headers).status_code == 410
    assert client.post('/sales-files/presign-upload', headers=super_headers, json={'filename': 'old.pdf'}).status_code == 410
    assert not storage.deleted
    _, employee = make_user()
    assert upload(client, employee, state).status_code == 403
    assert upload(client, admin_headers, state).status_code == 403
    assert listing(client, employee)['entries'][0]['asset']['asset_id'] == aid
    assert client.get('/sales-files/list?section=photos&include_archived=true', headers=employee).status_code == 403
    module, _, _ = make_module()
    assert client.patch(f'/admin/content/modules/{module.id}/assets/{aid}', headers=admin_headers,
                        json={'revision': module.content_revision, 'filename': 'stolen.pdf'}).status_code == 404


def test_sales_upload_replace_restore_and_archive_keep_originals(client, db, super_headers, make_user, storage):
    state = listing(client, super_headers)
    first = upload(client, super_headers, state, 'Расчёт.txt', b'original first')
    assert first.status_code == 201, first.text
    state = first.json(); entry = state['entries'][0]; aid = uuid.UUID(entry['asset']['asset_id'])
    original_key = db.get(ContentAsset, aid).object_key
    second = upload(client, super_headers, state, 'new.csv', b'A,B\n1,2', entry['id'])
    assert second.status_code == 201, second.text
    state = second.json(); entry = state['entries'][0]
    assert entry['name'] == 'Расчёт.csv' and entry['asset']['version'] == 2
    db.expire_all()
    current_key = db.get(ContentAsset, aid).object_key
    assert original_key != current_key and storage.objects[original_key] == b'original first'
    history = client.get(f"/sales-files/entries/{entry['id']}/versions", headers=super_headers).json()
    assert history['items'][0]['version'] == 1
    restored = client.post(f"/sales-files/entries/{entry['id']}/restore-version", headers=super_headers,
                           json={'revision': state['revision'], 'version': 1})
    assert restored.status_code == 200, restored.text
    state = restored.json(); entry = state['entries'][0]
    assert entry['name'] == 'Расчёт.txt' and entry['asset']['version'] == 3 and entry['asset']['asset_id'] == str(aid)
    assert storage.objects[current_key] == b'A,B\n1,2' and not storage.deleted
    archived = client.patch(f"/sales-files/entries/{entry['id']}", headers=super_headers, json={'revision': state['revision'], 'is_archived': True})
    assert archived.status_code == 200
    _, employee = make_user()
    assert not listing(client, employee)['entries']
    assert client.get(f'/assets/{aid}/download', headers=employee).status_code == 404
    assert upload(client, super_headers, archived.json(), 'Расчёт.txt').status_code == 409  # Restore, do not shadow an archived name.
    result = client.patch(f"/sales-files/entries/{entry['id']}", headers=super_headers,
                          json={'revision': archived.json()['revision'], 'is_archived': False})
    assert result.status_code == 200
    assert client.get(f'/assets/{aid}/download', headers=employee).content == b'original first'
    assert len(list(db.scalars(select(AssetRevision).where(AssetRevision.asset_id == aid)))) == 2


def test_archived_parent_blocks_all_asset_routes_and_restore_keeps_child_archive(client, db, super_headers, admin_headers, make_user, storage):
    storage.objects['sales/photos/Папка/Вложенная/image.png'] = b'picture'
    root = listing(client, super_headers)
    outer = root['entries'][0]
    listing(client, super_headers, 'Папка')
    leaf = listing(client, super_headers, 'Папка/Вложенная')
    file = leaf['entries'][0]; aid = file['asset']['asset_id']
    response = client.patch(f"/sales-files/entries/{outer['id']}", headers=super_headers,
                            json={'revision': leaf['revision'], 'is_archived': True})
    assert response.status_code == 200
    _, employee = make_user()
    for suffix in ('stream', 'download', 'preview', 'viewer', 'presign-download'):
        assert client.get(f'/assets/{aid}/{suffix}', headers=employee).status_code == 404
        assert client.get(f'/assets/{aid}/{suffix}', headers=admin_headers).status_code == 404
    assert client.get(f'/assets/{aid}/download', headers=super_headers).content == b'picture'
    assert client.patch(f"/sales-files/entries/{file['id']}", headers=super_headers,
                        json={'revision': response.json()['revision'], 'is_archived': False}).status_code == 409
    restored = client.patch(f"/sales-files/entries/{outer['id']}", headers=super_headers,
                            json={'revision': response.json()['revision'], 'is_archived': False})
    assert restored.status_code == 200
    assert client.get(f'/assets/{aid}/download', headers=employee).content == b'picture'
    child = client.patch(f"/sales-files/entries/{file['id']}", headers=super_headers,
                         json={'revision': restored.json()['revision'], 'is_archived': True}).json()
    parent = client.patch(f"/sales-files/entries/{outer['id']}", headers=super_headers,
                          json={'revision': child['revision'], 'is_archived': True}).json()
    client.patch(f"/sales-files/entries/{outer['id']}", headers=super_headers, json={'revision': parent['revision'], 'is_archived': False})
    assert client.get(f'/assets/{aid}/download', headers=employee).status_code == 404
    assert not storage.deleted


def test_revision_conflict_after_upload_deletes_only_own_staging(client, db, super_headers, storage, monkeypatch):
    storage.objects['sales/photos/keep.txt'] = b'keep'
    state = listing(client, super_headers)
    real_upload = storage.upload
    def concurrent_upload(**kwargs):
        real_upload(**kwargs)
        with SessionLocal() as other:
            other.get(SalesSection, 'photos').revision += 1
            other.commit()
    from app.routers import sales_files
    monkeypatch.setattr(sales_files, 'upload_fileobj_with_retry', concurrent_upload)
    result = upload(client, super_headers, state, 'new.txt')
    assert result.status_code == 409
    assert storage.objects['sales/photos/keep.txt'] == b'keep'
    assert storage.deleted == storage.uploaded and all(key.startswith('managed/sales/') for key in storage.deleted)


def test_legacy_listing_is_bounded_and_rename_cannot_hide_unadopted_original(client, super_headers, storage):
    for i in range(502):
        storage.objects[f'sales/photos/f{i:04}.txt'] = str(i).encode()
    state = listing(client, super_headers)
    assert state['total'] == 500 and len(state['entries']) == 100 and state['legacy_cursor']
    entry = state['entries'][0]
    rename = client.patch(f"/sales-files/entries/{entry['id']}", headers=super_headers,
                          json={'revision': state['revision'], 'name': 'f0501.txt'})
    assert rename.status_code == 409
    next_page = listing(client, super_headers, legacy_cursor=state['legacy_cursor'])
    assert next_page['total'] == 502 and next_page['legacy_cursor'] is None
    assert len(listing(client, super_headers, offset=500)['entries']) == 2
    assert storage.objects['sales/photos/f0501.txt'] == b'501'


def test_legacy_rename_and_archive_are_not_undone_by_rescan(client, super_headers, storage):
    storage.objects['sales/photos/old.txt'] = b'preserved'
    state = listing(client, super_headers); entry = state['entries'][0]
    rename = client.patch(f"/sales-files/entries/{entry['id']}", headers=super_headers,
                          json={'revision': state['revision'], 'name': 'renamed.txt'})
    assert rename.status_code == 200, rename.text
    state = listing(client, super_headers)
    assert [item['name'] for item in state['entries']] == ['renamed.txt']
    archived = client.patch(f"/sales-files/entries/{entry['id']}", headers=super_headers,
                            json={'revision': state['revision'], 'is_archived': True})
    assert archived.status_code == 200 and listing(client, super_headers)['entries'] == []
    assert storage.objects['sales/photos/old.txt'] == b'preserved'


def test_storage_transport_failure_is_actionable_and_cannot_hide_legacy_files(client, super_headers, storage, monkeypatch):
    state = listing(client, super_headers)
    def offline(**kwargs): raise TimeoutError('storage down')
    monkeypatch.setattr(storage, 'head_object', offline)
    response = upload(client, super_headers, state)
    assert response.status_code == 503 and not storage.uploaded


def test_folder_rename_moves_children_and_entry_move_changes_only_the_path(client, db, super_headers, storage):
    root = listing(client, super_headers)
    made = client.post('/sales-files/mkdir', headers=super_headers, json={
        'section': 'photos', 'path': '', 'name': 'Каталог', 'revision': root['revision']})
    assert made.status_code == 201, made.text
    state = made.json()
    folder = next(e for e in state['entries'] if e['kind'] == 'folder')
    assert state['folder_counts'][folder['path']] == 0
    inside = client.post('/sales-files/mkdir', headers=super_headers, json={
        'section': 'photos', 'path': folder['path'], 'name': 'Внутри', 'revision': state['revision']})
    assert inside.status_code == 201, inside.text
    state = inside.json()
    uploaded = upload(client, super_headers, {**state, 'path': folder['path']}, 'Прайс.txt', b'data')
    assert uploaded.status_code == 201, uploaded.text
    state = uploaded.json()
    assert {e['name'] for e in state['entries']} == {'Внутри', 'Прайс.txt'}
    assert any(e['name'] == 'Каталог' and listing(client, super_headers)['folder_counts'][e['path']] == 2 for e in listing(client, super_headers)['entries'])

    renamed = client.patch(f"/sales-files/entries/{folder['id']}", headers=super_headers,
                           json={'revision': state['revision'], 'name': 'Новый каталог'})
    assert renamed.status_code == 200, renamed.text
    state = renamed.json()
    names = {e['path'] for e in state['entries']}
    assert 'Новый каталог' in names
    children = listing(client, super_headers, path='Новый каталог')
    assert {e['name'] for e in children['entries']} == {'Внутри', 'Прайс.txt'}

    # Перенос файла в папку не меняет оригинал в хранилище.
    file_entry = next(e for e in children['entries'] if e['kind'] == 'file')
    key_before = db.get(ContentAsset, uuid.UUID(file_entry['asset']['asset_id'])).object_key
    moved = client.post(f"/sales-files/entries/{file_entry['id']}/move", headers=super_headers,
                        json={'revision': children['revision'], 'path': 'Новый каталог/Внутри'})
    assert moved.status_code == 200, moved.text
    assert db.get(ContentAsset, uuid.UUID(file_entry['asset']['asset_id'])).object_key == key_before
    assert db.scalar(select(SalesEntry).where(SalesEntry.id == uuid.UUID(file_entry['id']))).path == 'Новый каталог/Внутри'


def test_folder_cannot_be_moved_into_itself_and_needs_archive_before_delete(client, db, super_headers, storage):
    root = listing(client, super_headers)
    made = client.post('/sales-files/mkdir', headers=super_headers, json={
        'section': 'photos', 'path': '', 'name': 'Внешняя', 'revision': root['revision']})
    state = made.json()
    outer = next(e for e in state['entries'] if e['kind'] == 'folder')
    child = client.post('/sales-files/mkdir', headers=super_headers, json={
        'section': 'photos', 'path': outer['path'], 'name': 'Дочерняя', 'revision': state['revision']})
    state = child.json()
    inner = next(e for e in state['entries'] if e['kind'] == 'folder' and e['path'].startswith(outer['path']))
    loop = client.post(f"/sales-files/entries/{outer['id']}/move", headers=super_headers,
                       json={'revision': state['revision'], 'path': inner['path']})
    assert loop.status_code == 422

    uploaded = upload(client, super_headers, state, 'Договор.txt', b'contract')
    state = uploaded.json()
    file_entry = next(e for e in state['entries'] if e['kind'] == 'file')
    early = client.post(f"/sales-files/entries/{file_entry['id']}/delete", headers=super_headers,
                        json={'revision': state['revision']})
    assert early.status_code == 409

    key = db.get(ContentAsset, uuid.UUID(file_entry['asset']['asset_id'])).object_key
    archive = client.patch(f"/sales-files/entries/{file_entry['id']}", headers=super_headers,
                           json={'revision': state['revision'], 'is_archived': True})
    state = archive.json()
    removed = client.post(f"/sales-files/entries/{file_entry['id']}/delete", headers=super_headers,
                          json={'revision': state['revision']})
    assert removed.status_code == 200, removed.text
    assert db.scalar(select(SalesEntry).where(SalesEntry.id == uuid.UUID(file_entry['id']))) is None
    assert key in storage.deleted


def test_limit_is_shown_in_the_listing(client, super_headers):
    state = listing(client, super_headers)
    assert state['upload_max_bytes'] >= 1024 * 1024


def test_sales_file_arrives_in_chunks(client, db, super_headers, storage):
    state = listing(client, super_headers)
    blob = bytes(range(256)) * 30
    started = client.post('/sales-files/uploads', headers=super_headers, json={
        'section': 'photos', 'path': '', 'revision': state['revision'],
        'filename': 'Съёмка.jpg', 'size_bytes': len(blob)})
    assert started.status_code == 201, started.text
    upload_id, offset = started.json()['upload_id'], 0
    while offset < len(blob):
        pushed = client.put(f'/sales-files/uploads/{upload_id}?offset={offset}', headers=super_headers,
                            content=blob[offset:offset + 1000])
        assert pushed.status_code == 200, pushed.text
        offset = pushed.json()['offset']
    done = client.post(f'/sales-files/uploads/{upload_id}/complete', headers=super_headers)
    assert done.status_code == 200, done.text
    entry = next(e for e in done.json()['entries'] if e['name'] == 'Съёмка.jpg')
    assert entry['asset']['size_bytes'] == len(blob)
    assert any(value == blob for value in storage.objects.values())
