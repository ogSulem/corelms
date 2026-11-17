"""Все роли в типе `userrole`: employee, partner, admin, superadmin.

Рабочая база пришла из более ранней схемы, где тип `userrole` не содержал
значения `employee`. Прежние миграции добавляли значения только из «своего»
списка (`0008` — employee и admin, `0020` — superadmin, `0025` — partner) и
каждая проверяла наличие лишь у себя, поэтому недостающее значение могло
отсутствовать в базе с уже применёнными миграциями.

Последствие: `INSERT INTO users (... role ...)` с ролью `employee` падал
(`invalid input value for enum userrole: "employee"`), и добавление партнёра
через админку не работало никогда — только отвечало 503 «база перегружена».

Здесь тип приводится к набору, который использует приложение. Данные не
меняются: значения только добавляются, а `IF NOT EXISTS` делает повторный
запуск безопасным.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-17
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

REQUIRED_ROLES = ("employee", "partner", "admin", "superadmin")


def upgrade() -> None:
    # `ALTER TYPE ... ADD VALUE` нельзя выполнять внутри транзакции до PG 12,
    # поэтому используем autocommit-блок (как в 0029 с CONCURRENTLY).
    with op.get_context().autocommit_block():
        for value in REQUIRED_ROLES:
            op.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres не умеет удалять значения enum, а пользователи с этими ролями
    # должны остаться читаемыми.
    pass
