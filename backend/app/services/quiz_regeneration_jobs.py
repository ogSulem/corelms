"""Compatibility tombstones: previously queued jobs must not publish unchecked tests.

RQ stores these import paths in Redis. Keep the paths, but fail explicitly before
any database, storage or AI work. Authors use services.authoring draft jobs now.
"""

_MESSAGE = "Старая автопубликация тестов отключена. Откройте модуль → Тесты → AI-черновик, проверьте вопросы и сохраните их явно."


def regenerate_submodule_quiz_job(*args, **kwargs):
    raise RuntimeError(_MESSAGE)


def regenerate_module_quizzes_job(*args, **kwargs):
    raise RuntimeError(_MESSAGE)
