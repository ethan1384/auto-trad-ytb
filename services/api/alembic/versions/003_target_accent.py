"""add project target_accent

Revision ID: 003_target_accent
Revises: 002_include_subtitles
Create Date: 2026-09-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_target_accent"
down_revision: Union[str, None] = "002_include_subtitles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("target_accent", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "target_accent")
