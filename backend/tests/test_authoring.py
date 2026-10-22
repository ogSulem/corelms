import json
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models.asset import ContentAsset
from app.models.attempt import QuizAttemptAnswer
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.tag import Tag, UserTagMap
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
