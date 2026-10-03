"""store the celery task id so a running job can be stopped

Revision ID: 004_job_celery_task
Revises: 003_target_accent
Create Date: 2026-09-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_job_celery_task"
down_revision: Union[str, None] = "003_target_accent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("celery_task_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "celery_task_id")
