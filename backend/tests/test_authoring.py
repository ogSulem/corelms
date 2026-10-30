import io
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models.asset import ContentAsset
from app.models.media import AssetRendition
from app.models.attempt import QuizAttempt, QuizAttemptAnswer
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.tag import Tag, UserTagMap
from app.core.config import settings
from app.services import authoring
from test_quiz_lifecycle import start, submit


def quiz_body(revision, **kwargs):
    return {"revision": revision, "enabled": True, "pass_threshold": 70, "time_limit": None, "attempts_limit": 3,
            "questions": [{"type": "single", "stem": "Что нужно сделать перед отправкой?", "options": ["Проверить данные", "Удалить расчёт"], "correct": [0], "explanation": "Проверка предотвращает ошибки."}], **kwargs}


def test_one_editor_creates_lesson_quiz_from_scratch_and_final_is_optional(client, admin_headers):
    created = client.post('/admin/content/modules', headers=admin_headers, json={"title": "Новый модуль с нуля"}).json()
    base = '/admin/content/modules/' + created['module']['id']
    added = client.post(base + '/lessons', headers=admin_headers, json={"revision": created['module']['content_revision'], "title": "Первый урок", "content": "Полезный текст для обучения"}).json()
    lesson = added['lessons'][0]
    assert lesson['presentation_mode'] == 'auto' and not lesson['requires_quiz']
    assert client.get(base + f"/lessons/{lesson['id']}/quiz", headers=admin_headers).json()['questions'] == []
    saved = client.put(base + f"/lessons/{lesson['id']}/quiz", headers=admin_headers, json=quiz_body(added['module']['content_revision']))
    assert saved.status_code == 200, saved.text
    data = saved.json()
    assert data['quiz']['questions'][0]['correct'] == [0] and data['quiz']['enabled']
    assert data['workspace']['module']['final_quiz_id'] is None
    final = client.put(base + '/final-quiz', headers=admin_headers, json={"revision": data['workspace']['module']['content_revision'], "enabled": True})
    assert final.status_code == 200 and final.json()['module']['final_quiz_id']
    final_id = final.json()['module']['final_quiz_id']
    disabled = client.put(base + '/final-quiz', headers=admin_headers, json={"revision": final.json()['module']['content_revision'], "enabled": False})
    assert disabled.json()['module']['final_quiz_id'] == final_id and not disabled.json()['module']['final_quiz_enabled']


@pytest.mark.parametrize('question', [
    {"type": "single", "stem": "Вопрос\nA) Лишний встроенный вариант", "options": ["Да", "Нет"], "correct": [0]},
    {"type": "single", "stem": "Вопрос", "options": ["Ответ\nB) Встроенный список", "Нет"], "correct": [0]},
    {"type": "case", "stem": "Любой ответ", "options": ["Да", "Нет"], "correct": [0]},
    {"type": "single", "stem": "", "options": ["Да", "Нет"], "correct": [0]},
    {"type": "single", "stem": "Вопрос", "options": ["Да", " да "], "correct": [0]},
    {"type": "single", "stem": "Вопрос", "options": ["Да", "Нет"], "correct": [0, 1]},
    {"type": "multi", "stem": "Вопрос", "options": ["Да", "Нет"], "correct": [2]},
    {"type": "multi", "stem": "Вопрос", "options": ["Да", "Нет"], "correct": []},
])
def test_question_validation_is_structured(client, admin_headers, make_module, question):
    module, lesson, _ = make_module()
    response = client.put(f'/admin/content/modules/{module.id}/lessons/{lesson.id}/quiz', headers=admin_headers,
                          json=quiz_body(module.content_revision, questions=[question]))
    assert response.status_code == 422


def test_bulk_save_is_scoped_revision_checked_and_copy_on_write(client, db, admin_headers, make_module, make_user):
    module, lesson, old_quiz = make_module(required=True)
    _, headers = make_user()
    active = start(client, headers, lesson, old_quiz)
    old_question = active['questions'][0]['id']
    base = f'/admin/content/modules/{module.id}/lessons/{lesson.id}/quiz'
    changed = client.put(base, headers=admin_headers, json=quiz_body(module.content_revision))
    assert changed.status_code == 200, changed.text
    new_id = changed.json()['quiz']['quiz_id']
    assert new_id != str(old_quiz.id)
    assert client.put(base, headers=admin_headers, json=quiz_body(module.content_revision)).status_code == 409
    other, other_lesson, _ = make_module()
    assert client.put(f'/admin/content/modules/{other.id}/lessons/{lesson.id}/quiz', headers=admin_headers,
                      json=quiz_body(other.content_revision)).status_code == 404
    assert client.put(base, headers=headers, json=quiz_body(changed.json()['quiz']['revision'])).status_code == 403
    result = submit(client, headers, old_quiz.id, active)
    assert result['passed']
    assert db.scalar(select(func.count()).select_from(QuizAttemptAnswer).where(QuizAttemptAnswer.question_id == uuid.UUID(old_question))) == 1
    assert client.get(f'/progress/modules/{module.id}', headers=headers).json()['completed']
    current = start(client, headers, lesson, SimpleNamespace(id=new_id))
    assert submit(client, headers, new_id, current)['xp_awarded'] == 0


def test_final_session_keeps_threshold_timer_and_limit_at_start(client, db, admin_headers, make_module, make_user, redis_memory):
    module, lesson, quiz = make_module(required=True, final=True, question_count=2)
    final = db.get(Quiz, module.final_quiz_id)
    final.pass_threshold, final.time_limit = 50, 120
    db.commit()
    _, headers = make_user()
    initial = start(client, headers, lesson, quiz)
    submit(client, headers, quiz.id, initial)
    active = client.post(f'/quizzes/{final.id}/start', headers=headers).json()
    assert active['pass_threshold'] == 50
    key = next(k for k in redis_memory.scan_iter('quiz_session:*') if k.endswith(str(final.id)))
    raw = json.loads(redis_memory.get(key)); raw['started_at'] = int(time.time()) - 65
    redis_memory.set(key, json.dumps(raw), ex=3600)
    db.refresh(module)
    updated = client.put(f'/admin/content/modules/{module.id}/final-quiz', headers=admin_headers,
                         json={"revision": module.content_revision, "enabled": True, "pass_threshold": 100, "time_limit": 60, "attempts_limit": 1})
    assert updated.status_code == 200, updated.text
    resumed = client.post(f'/quizzes/{final.id}/start', headers=headers)
    assert resumed.status_code == 200 and resumed.json()['session_id'] == active['session_id']
    assert resumed.json()['pass_threshold'] == 50 and resumed.json()['time_limit'] == 120 and resumed.json()['attempts_limit'] == 3
    result = client.post(f'/quizzes/{final.id}/submit', headers=headers, json={"session_id": active['session_id'], "answers": [
        {"question_id": q['id'], "answer": 'A' if i == 0 else 'B'} for i, q in enumerate(active['questions'])]})
    assert result.status_code == 200 and result.json()['score'] == 50 and result.json()['passed']


def test_review_is_owner_only_and_never_reveals_answers_before_pass_or_exhaustion(client, db, make_module, make_user):
    _, lesson, quiz = make_module(required=True)
    question = db.scalar(select(Question).where(Question.quiz_id == quiz.id)); question.explanation = 'Объяснение правильного решения'
    db.commit()
    _, headers = make_user(); _, stranger = make_user()
    url = f'/quizzes/{quiz.id}/attempts/latest'
    assert client.get(url, headers=headers).json()['attempt'] is None
    first = start(client, headers, lesson, quiz); submit(client, headers, quiz.id, first, 'B')
    locked = client.get(url, headers=headers).json()
    assert not locked['can_review'] and 'correct_answer' not in locked['questions'][0] and 'explanation' not in locked['questions'][0]
    assert client.get(url, headers=stranger).json()['attempt'] is None
    second = start(client, headers, lesson, quiz); submit(client, headers, quiz.id, second)
    review = client.get(url, headers=headers).json()
    assert review['can_review'] and review['questions'][0]['correct_answer'] == 'A' and review['questions'][0]['explanation']


def test_any_free_text_is_not_a_knowledge_check(client, db, make_module, make_user):
    _, lesson, quiz = make_module(required=True)
    q = db.scalar(select(Question).where(Question.quiz_id == quiz.id))
    q.type, q.correct_answer = QuestionType.case, 'ANY'; db.commit()
    _, headers = make_user()
    client.post(f'/submodules/{lesson.id}/read', headers=headers)
    assert client.post(f'/quizzes/{quiz.id}/start', headers=headers).status_code == 409
    from app.routers.quizzes import _is_correct
    assert not _is_correct(question=q, answer='случайный непустой ответ')


def test_presentation_primary_file_scope_and_tag_access(client, db, admin_headers, make_module, make_user, storage):
    module, lesson, _ = make_module()
    other, other_lesson, _ = make_module()
    asset = ContentAsset(module_id=module.id, bucket='testing', object_key='a.pdf', original_filename='a.pdf')
    wrong = ContentAsset(module_id=other.id, bucket='testing', object_key='b.pdf', original_filename='b.pdf')
    db.add_all([asset, wrong]); db.flush()
    db.add_all([SubmoduleAssetMap(asset_id=asset.id, submodule_id=lesson.id, order=1), SubmoduleAssetMap(asset_id=wrong.id, submodule_id=other_lesson.id, order=1)])
    tag = Tag(name='Команда'); db.add(tag); db.commit()
    base = f'/admin/content/modules/{module.id}'
    body = {"revision": module.content_revision, "presentation_mode": 'material', 'primary_asset_id': str(wrong.id)}
    assert client.patch(base + f'/lessons/{lesson.id}', headers=admin_headers, json=body).status_code == 404
    body['primary_asset_id'] = str(asset.id)
    result = client.patch(base + f'/lessons/{lesson.id}', headers=admin_headers, json=body)
    assert result.status_code == 200 and result.json()['lessons'][0]['primary_asset_id'] == str(asset.id)
    revision = result.json()['module']['content_revision']
    changed = client.patch(base, headers=admin_headers, json={"revision": revision, 'visibility': 'restricted', 'tag_ids': [str(tag.id)]})
    assert changed.status_code == 200
    learner, headers = make_user()
    assert client.get(f'/submodules/{lesson.id}', headers=headers).status_code == 404
    db.add(UserTagMap(user_id=learner.id, tag_id=tag.id)); db.commit()
    data = client.get(f'/submodules/{lesson.id}', headers=headers).json()
    assert data['presentation_mode'] == 'material' and data['primary_asset_id'] == str(asset.id)


def test_ai_returns_reviewable_draft_and_never_mutates_live_bank(db, make_module, monkeypatch):
    module, lesson, quiz = make_module(required=True, content='Содержательный текст урока. ' * 50)
    before = list(db.scalars(select(Question.id).where(Question.quiz_id == quiz.id)))
    monkeypatch.setattr(authoring, 'generate_quiz_questions_ai', lambda **kw: [SimpleNamespace(type='single', prompt='Что проверить?\nA) Данные\nB) Цвет стола', correct_answer='A', explanation='Проверьте данные.')])
    result = authoring.generate_quiz_draft_job(str(module.id), str(lesson.id), module.content_revision, 5)
    assert result['ok'] and result['needs_review'] and result['questions'][0]['correct'] == [0]
    db.expire_all()
    assert db.get(Submodule, lesson.id).quiz_id == quiz.id
    assert list(db.scalars(select(Question.id).where(Question.quiz_id == quiz.id))) == before
    assert db.get(Module, module.id).content_revision == result['revision']
    assert not authoring.generate_quiz_draft_job(str(module.id), str(lesson.id), module.content_revision, 5, source_text='')['ok']
    monkeypatch.setattr(authoring, 'generate_quiz_questions_ai', lambda **kw: [])
    assert not authoring.generate_quiz_draft_job(str(module.id), str(lesson.id), module.content_revision, 5)['ok']
    assert not authoring.generate_quiz_draft_job(str(module.id), str(lesson.id), module.content_revision - 1, 5)['ok']


def test_deprecated_generation_no_longer_silently_publishes(client, admin_headers, make_module):
    module, lesson, _ = make_module()
    assert client.post(f'/admin/modules/{module.id}/regenerate-quizzes', headers=admin_headers).status_code == 410
    assert client.post(f'/admin/submodules/{lesson.id}/regenerate-quiz', headers=admin_headers).status_code == 410
    response = client.post(f'/admin/content/modules/{module.id}/lessons/{lesson.id}/quiz-draft', headers=admin_headers,
                           json={"revision": module.content_revision})
    assert response.status_code == 503


def test_large_lesson_workspace_is_bounded_but_editor_can_load_full_text(client, db, admin_headers, make_module):
    full_text = 'Содержательная инструкция.\n' * 3000
    module, lesson, _ = make_module(content=full_text)
    base = f'/admin/content/modules/{module.id}'
    workspace = client.get(base, headers=admin_headers).json()
    assert len(workspace['lessons'][0]['content']) == 4000 and workspace['lessons'][0]['has_external_content']
    assert workspace['lessons'][0]['content_length'] == len(full_text)
    complete = client.get(base + f'/lessons/{lesson.id}/content', headers=admin_headers).json()
    assert complete['content'] == full_text
    changed = client.patch(base + f'/lessons/{lesson.id}', headers=admin_headers,
        json={'revision': workspace['module']['content_revision'], 'presentation_mode': 'text'})
    assert changed.status_code == 200
    db.expire_all(); assert db.get(Submodule, lesson.id).content == full_text


def test_ai_uses_primary_document_or_explicit_text_mode_not_an_incidental_attachment(db, make_module, storage):
    module, lesson, _ = make_module(content='Ручной текст урока. ' * 100)
    for index in range(2):
        text = f'Содержимое документа {index}. ' * 100
        asset = ContentAsset(module_id=module.id, bucket='testing', object_key=f'doc-{index}.txt', original_filename=f'doc-{index}.txt', size_bytes=len(text.encode()))
        db.add(asset); db.flush(); db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=index + 1))
        storage.objects[asset.object_key] = text.encode()
        if index == 1: lesson.primary_asset_id = asset.id
    db.commit()
    text, source = authoring._source_text(db, lesson)
    assert text.startswith('Содержимое документа 1') and 'doc-1.txt' in source
    lesson.presentation_mode = 'text'; db.commit()
    text, source = authoring._source_text(db, lesson)
    assert text.startswith('Ручной текст') and 'Текст урока' in source


def test_uncheckable_legacy_attempt_does_not_consume_attempt_or_award_points(client, db, make_module, make_user):
    _, lesson, quiz = make_module(required=True)
    _, headers = make_user(); active = start(client, headers, lesson, quiz)
    question = db.scalar(select(Question).where(Question.quiz_id == quiz.id))
    question.type, question.correct_answer = QuestionType.case, 'ANY'; db.commit()
    response = client.post(f'/quizzes/{quiz.id}/submit', headers=headers, json={'session_id': active['session_id'],
        'answers': [{'question_id': active['questions'][0]['id'], 'answer': 'Любой ответ'}]})
    assert response.status_code == 409
    assert client.get(f'/quizzes/{quiz.id}/attempts/latest', headers=headers).json()['attempt'] is None


def test_draft_status_is_recoverable_after_lost_enqueue_reply_and_outage_is_not_expiry(client, db, admin_headers, make_module, monkeypatch):
    from app.routers import content
    from app.core.config import settings
    module, lesson, _ = make_module()
    monkeypatch.setattr(settings, 'openrouter_api_key', 'synthetic-test-key')
    url = f'/admin/content/modules/{module.id}/lessons/{lesson.id}/quiz-draft'
    registry, calls = {}, []
    def enqueue(fn, *args, **kwargs):
        calls.append(1)
        job = SimpleNamespace(id=kwargs['job_id'], meta=kwargs['meta'], get_status=lambda **kw: 'queued')
        registry[job.id] = job
        raise ConnectionError('Response lost after enqueue')
    monkeypatch.setattr(content, 'get_queue', lambda _name: SimpleNamespace(enqueue=enqueue))
    monkeypatch.setattr(content, 'fetch_job', lambda job_id, **kw: registry.get(job_id))
    response = client.post(url, headers=admin_headers, json={'revision': module.content_revision})
    assert response.status_code == 503
    status = client.get(url, headers=admin_headers)
    assert status.status_code == 200 and status.json()['status'] == 'queued'
    again = client.post(url, headers=admin_headers, json={'revision': module.content_revision})
    assert again.status_code == 202 and again.json()['existing'] and len(calls) == 1
    def offline(*args, **kwargs): raise ConnectionError()
    monkeypatch.setattr(content, 'fetch_job', offline)
    assert client.get(url, headers=admin_headers).status_code == 503
    db.expire_all(); assert db.get(Submodule, lesson.id).quiz_id == lesson.quiz_id


def test_provider_validation_never_invents_an_explanation():
    from app.services.openrouter import OpenRouterQuestion, _is_good_question
    question = OpenRouterQuestion(type='single', prompt='Что нужно уточнить у клиента?\nA) Задачу\nB) Погоду\nC) Цвет папки\nD) День недели', correct_answer='A')
    assert _is_good_question(question, seen_prompts=set())
    assert question.explanation is None


def test_module_batch_reports_automation_in_one_transaction(redis_memory, monkeypatch, db, make_module):
    import rq
    from app.services import quiz_drafts
    module, first, _ = make_module()
    second_quiz = Quiz(type=QuizType.submodule)
    db.add(second_quiz); db.flush()
    second = Submodule(module_id=module.id, title='Второй урок', order=2, quiz_id=second_quiz.id, requires_quiz=False)
    db.add(second); db.commit()
    # RQ stores binary job hashes: use a non-decoding connection, as production does.
    import fakeredis
    raw = fakeredis.FakeRedis()
    queue = rq.Queue('test-batch', connection=raw)
    monkeypatch.setattr(quiz_drafts, 'get_queue', lambda _name: queue)
    monkeypatch.setattr(quiz_drafts, 'get_redis', lambda: raw)
    monkeypatch.setattr(settings, 'openrouter_api_key', 'synthetic-key-for-tests')
    missing = quiz_drafts.prepare_module_drafts(db, module, actor_id=uuid.uuid4(), count=4, only_missing=True)
    assert len(missing['items']) == 1 and missing['items'][0]['lesson_id'] == str(second.id)
    receipt = quiz_drafts.prepare_module_drafts(db, module, actor_id=uuid.uuid4(), count=4, only_missing=False)
    assert len(receipt['items']) == 2 and receipt['remaining'] == 0
    assert raw.get(f"authoring:batch:{module.id}:latest").decode() == receipt['id']
    for item in receipt['items']:
        assert raw.get(f"authoring:draft:{module.id}:{item['lesson_id']}").decode() == item['job_id']
    status = quiz_drafts.module_draft_status(db, module)
    assert status['working'] is True and status['counts'] == {'queued': 1, 'configured': 1}
    # Re-running with the same source does not enqueue duplicate AI work.
    again = quiz_drafts.prepare_module_drafts(db, module, actor_id=uuid.uuid4(), count=4, only_missing=False)
    assert all(item['reused'] for item in again['items']) and len(again['items']) == 2


def test_editing_another_lesson_or_the_bank_does_not_invalidate_source_fingerprint(db, make_module, storage):
    from app.services.authoring import source_revision
    module, lesson, quiz = make_module(required=True)
    other_quiz = Quiz(type=QuizType.submodule)
    db.add(other_quiz); db.flush()
    other = Submodule(module_id=module.id, title='Другой', order=2, quiz_id=other_quiz.id)
    db.add(other); db.commit()
    before = source_revision(db, lesson)
    other.content = 'Изменился только другой урок'
    quiz.pass_threshold = 90
    module.is_active = False
    module.content_revision += 5
    db.commit()
    assert source_revision(db, lesson) == before
    lesson.presentation_mode = 'text'
    db.commit()
    assert source_revision(db, lesson) != before


def test_new_lesson_from_a_file_is_ready_to_read(client, db, admin_headers, make_module, storage):
    module, _, _ = make_module()
    response = client.post(f'/admin/content/modules/{module.id}/assets', headers=admin_headers,
        data={'revision': str(module.content_revision), 'create_lesson': 'true'},
        files={'file': ('Регламент продаж.docx', io.BytesIO(b'PK\x03\x04synthetic'), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code == 201, response.text
    state = response.json()
    lesson = db.get(Submodule, uuid.UUID(state['created_lesson_id']))
    assert lesson.title == 'Регламент продаж' and lesson.presentation_mode == 'material' and lesson.requires_quiz is False
    assert str(lesson.primary_asset_id) == state['assets'][0]['asset_id']


def _upload_file(client, headers, module, name="Прайс.xlsx", content=b"PK\x03\x04synthetic"):
    response = client.post(f'/admin/content/modules/{module.id}/assets', headers=headers,
        data={'revision': str(module.content_revision)},
        files={'file': (name, io.BytesIO(content), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code == 201, response.text
    return response.json()


def test_file_moves_into_a_catalog_and_a_folder(client, db, admin_headers, make_module, storage):
    module, lesson, _ = make_module()
    state = _upload_file(client, admin_headers, module)
    asset_id = state['assets'][0]['asset_id']
    created = client.post(f'/admin/content/modules/{module.id}/lessons', headers=admin_headers,
        json={'revision': state['module']['content_revision'], 'title': 'Каталог производства', 'is_folder': True})
    assert created.status_code == 201, created.text
    state = created.json()
    catalog_id = state['lessons'][-1]['id']
    moved = client.post(f'/admin/content/modules/{module.id}/assets/move', headers=admin_headers, json={
        'revision': state['module']['content_revision'], 'ids': [asset_id],
        'submodule_id': catalog_id, 'folder': 'Производство / Сварка'})
    assert moved.status_code == 200, moved.text
    asset = next(a for a in moved.json()['assets'] if a['asset_id'] == asset_id)
    assert asset['submodule_id'] == catalog_id
    assert asset['original_filename'] == 'Производство/Сварка/Прайс.xlsx'
    # Возврат в корень каталога: пустая папка.
    state = client.post(f'/admin/content/modules/{module.id}/assets/move', headers=admin_headers, json={
        'revision': moved.json()['module']['content_revision'], 'ids': [asset_id], 'folder': ''})
    assert state.status_code == 200, state.text
    assert next(a for a in state.json()['assets'] if a['asset_id'] == asset_id)['original_filename'] == 'Прайс.xlsx'


def test_rename_keeps_the_folder(client, db, admin_headers, make_module, storage):
    module, lesson, _ = make_module()
    state = _upload_file(client, admin_headers, module)
    asset_id = state['assets'][0]['asset_id']
    placed = client.post(f'/admin/content/modules/{module.id}/assets/move', headers=admin_headers, json={
        'revision': state['module']['content_revision'], 'ids': [asset_id], 'folder': 'Папка'})
    assert placed.status_code == 200, placed.text
    renamed = client.patch(f'/admin/content/modules/{module.id}/assets/{asset_id}', headers=admin_headers,
        json={'revision': placed.json()['module']['content_revision'], 'filename': 'Новый прайс.xlsx'})
    assert renamed.status_code == 200, renamed.text
    assert next(a for a in renamed.json()['assets'] if a['asset_id'] == asset_id)['original_filename'] == 'Папка/Новый прайс.xlsx'


def test_archived_file_is_deleted_forever_with_its_versions(client, db, admin_headers, make_module, storage):
    module, lesson, _ = make_module()
    state = _upload_file(client, admin_headers, module)
    asset_id = state['assets'][0]['asset_id']
    key = db.get(ContentAsset, uuid.UUID(asset_id)).object_key
    active = client.post(f'/admin/content/modules/{module.id}/assets/delete', headers=admin_headers,
        json={'revision': state['module']['content_revision'], 'ids': [asset_id]})
    assert active.status_code == 409  # активный файл сначала убирают из обучения
    archived = client.post(f'/admin/content/modules/{module.id}/assets/archive', headers=admin_headers,
        json={'revision': state['module']['content_revision'], 'ids': [asset_id], 'is_archived': True})
    assert archived.status_code == 200, archived.text
    removed = client.post(f'/admin/content/modules/{module.id}/assets/delete', headers=admin_headers,
        json={'revision': archived.json()['module']['content_revision'], 'ids': [asset_id]})
    assert removed.status_code == 200, removed.text
    assert all(a['asset_id'] != asset_id for a in removed.json()['assets'])
    assert db.get(ContentAsset, uuid.UUID(asset_id)) is None
    assert key in storage.deleted


def test_workspace_marks_assets_that_have_a_ready_browser_copy(client, db, admin_headers, make_module, storage):
    module, _, _ = make_module()
    state = _upload_file(client, admin_headers, module)
    asset_id = state['assets'][0]['asset_id']
    assert state['assets'][0]['browser_copy'] is False
    asset = db.get(ContentAsset, uuid.UUID(asset_id))
    db.add(AssetRendition(asset_id=asset.id, source_version=asset.version, source_bucket=asset.bucket,
        source_object_key=asset.object_key, state='ready', bucket=asset.bucket,
        object_key='renditions/copy.pdf', mime_type='application/pdf'))
    db.commit()
    fresh = client.get(f'/admin/content/modules/{module.id}', headers=admin_headers).json()
    assert fresh['assets'][0]['browser_copy'] is True


def test_final_quiz_shows_its_composition_and_sample(client, db, admin_headers, make_module):
    module, lesson, quiz = make_module(required=True)
    empty = client.get(f'/admin/content/modules/{module.id}/final-quiz', headers=admin_headers)
    assert empty.status_code == 200, empty.text
    data = empty.json()
    assert data['questions'] == []  # собственного банка у итогового теста нет
    assert data['source_lessons'] == 1
    row = next(item for item in data['lessons'] if item['id'] == str(lesson.id))
    assert row['contributes'] and row['question_count'] >= 1
    assert data['max_questions'] >= 1
    assert data['sample'] and data['sample'][0]['lesson'] == lesson.title
    assert data['sample'][0]['options']


def test_archived_lesson_without_history_is_deleted_and_its_files_stay_archived(client, db, admin_headers, make_module, storage):
    module, lesson, _ = make_module()
    state = _upload_file(client, admin_headers, module)
    asset_id = state['assets'][0]['asset_id']
    client.post(f'/admin/content/modules/{module.id}/assets/move', headers=admin_headers, json={
        'revision': state['module']['content_revision'], 'ids': [asset_id], 'submodule_id': str(lesson.id), 'folder': ''})
    current = client.get(f'/admin/content/modules/{module.id}', headers=admin_headers).json()
    archived = client.patch(f'/admin/content/modules/{module.id}/lessons/{lesson.id}', headers=admin_headers,
        json={'revision': current['module']['content_revision'], 'is_archived': True})
    assert archived.status_code == 200, archived.text
    removed = client.post(f'/admin/content/modules/{module.id}/lessons/{lesson.id}/delete', headers=admin_headers,
        json={'revision': archived.json()['module']['content_revision']})
    assert removed.status_code == 200, removed.text
    state = removed.json()
    assert all(item['id'] != str(lesson.id) for item in state['lessons'])
    assert db.scalar(select(func.count()).select_from(Submodule).where(Submodule.id == lesson.id)) == 0
    # Файл не исчез вместе с уроком: он в архиве модуля.
    kept = next(a for a in state['assets'] if a['asset_id'] == asset_id)
    assert kept['is_archived'] is True


def test_lesson_with_history_cannot_be_deleted_but_stays_in_archive(client, db, admin_headers, make_module, make_user):
    module, lesson, quiz = make_module()
    learner, headers = make_user()
    db.add(QuizAttempt(user_id=learner.id, quiz_id=quiz.id, started_at=func.now()))
    module.content_revision += 1
    lesson.is_archived = True
    db.commit()
    response = client.post(f'/admin/content/modules/{module.id}/lessons/{lesson.id}/delete', headers=admin_headers,
        json={'revision': module.content_revision})
    assert response.status_code == 409
    assert 'архивировать' in response.json()['error_message']
    assert db.scalar(select(func.count()).select_from(Submodule).where(Submodule.id == lesson.id)) == 1


def test_module_rename_uses_fresh_revision_after_an_upload(client, db, admin_headers, make_module, storage):
    """Загрузка файла поднимает редакцию модуля: форма настроек должна отправлять актуальную,
    иначе переименование модуля падает с 409 «Модуль изменён»."""
    module, _, _ = make_module()
    before = module.content_revision
    upload = client.post(f'/admin/content/modules/{module.id}/assets', headers=admin_headers,
        data={'revision': str(before)},
        files={'file': ('Прайс.xlsx', io.BytesIO(b'PK\x03\x04synthetic'), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert upload.status_code == 201, upload.text
    fresh = upload.json()['module']['content_revision']
    assert fresh != before
    stale = client.patch(f'/admin/content/modules/{module.id}', headers=admin_headers, json={'revision': before, 'title': 'Новое имя'})
    assert stale.status_code == 409
    renamed = client.patch(f'/admin/content/modules/{module.id}', headers=admin_headers, json={'revision': fresh, 'title': 'Новое имя'})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()['module']['title'] == 'Новое имя'


def test_grading_requires_exact_option_letters(client, db, make_module, make_user):
    from app.routers.quizzes import _is_correct
    _, lesson, quiz = make_module(required=True)
    question = db.scalar(select(Question).where(Question.quiz_id == quiz.id))
    assert _is_correct(question=question, answer='A')
    assert _is_correct(question=question, answer='а)')
    assert _is_correct(question=question, answer=' (A). ')
    assert not _is_correct(question=question, answer='A1 склад')
    assert not _is_correct(question=question, answer='AB')
    assert not _is_correct(question=question, answer='')


def test_context_suggests_the_next_real_step(client, db, admin_headers, make_module, make_user):
    module, lesson, quiz = make_module(required=True)
    _, headers = make_user()
    assert client.get(f'/quizzes/{quiz.id}/context', headers=headers).json()['next_step']['kind'] == 'lesson'
    assert client.post(f'/submodules/{lesson.id}/read', headers=headers).status_code == 200
    context = client.get(f'/quizzes/{quiz.id}/context', headers=headers).json()
    assert context['next_step']['kind'] == 'quiz' and context['next_step']['href'] == f'/quizzes/{quiz.id}'


def test_historical_quiz_context_never_offers_a_new_attempt_after_bank_replacement(client, db, admin_headers, make_module, make_user):
    module, lesson, old = make_module(required=True)
    _, headers = make_user()
    client.post(f'/submodules/{lesson.id}/read', headers=headers)
    saved = client.put(f'/admin/content/modules/{module.id}/lessons/{lesson.id}/quiz', headers=admin_headers,
                       json=quiz_body(module.content_revision))
    assert saved.status_code == 200
    context = client.get(f'/quizzes/{old.id}/context', headers=headers).json()
    assert context['can_start'] is False and 'актуальную' in (context['start_blocked_reason'] or '')


def test_draft_is_stale_only_when_this_lessons_materials_change(client, db, admin_headers, make_module, redis_memory, monkeypatch):
    from app.routers import content
    from app.services.authoring import source_revision
    module, lesson, _ = make_module()
    other_quiz = Quiz(type=QuizType.submodule)
    db.add(other_quiz); db.flush()
    other = Submodule(module_id=module.id, title='Другой', order=2, quiz_id=other_quiz.id)
    db.add(other); db.commit()
    job = SimpleNamespace(id='synthetic-job', meta={'job_kind': 'quiz_draft', 'module_id': str(module.id),
        'lesson_id': str(lesson.id), 'source_revision': source_revision(db, lesson), 'revision': module.content_revision},
        result={'ok': True, 'questions': []}, get_status=lambda **kwargs: 'finished')
    monkeypatch.setattr(content, 'get_redis', lambda: redis_memory)
    monkeypatch.setattr(content, 'fetch_job', lambda job_id, **kwargs: job)
    redis_memory.set(f'authoring:draft:{module.id}:{lesson.id}', 'synthetic-job')
    url = f'/admin/content/modules/{module.id}/lessons/{lesson.id}/quiz-draft'
    assert client.get(url, headers=admin_headers).json()['stale'] is False
    revision = client.get(f'/admin/content/modules/{module.id}', headers=admin_headers).json()['module']['content_revision']
    edited_other = client.patch(f'/admin/content/modules/{module.id}/lessons/{other.id}', headers=admin_headers,
        json={'revision': revision, 'content': 'Изменены только материалы другого урока'})
    assert edited_other.status_code == 200
    assert client.get(url, headers=admin_headers).json()['stale'] is False
    revision = edited_other.json()['module']['content_revision']
    edited_own = client.patch(f'/admin/content/modules/{module.id}/lessons/{lesson.id}', headers=admin_headers,
        json={'revision': revision, 'content': 'Теперь изменился сам источник черновика'})
    assert edited_own.status_code == 200
    assert client.get(url, headers=admin_headers).json()['stale'] is True
