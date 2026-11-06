"""${message}

Revision: ${up_revision} (down: ${down_revision | comma,n})
Zero-downtime rules (02/D3): expand -> backfill in batches -> contract; CREATE INDEX CONCURRENTLY;
lock_timeout before DDL; constraints NOT VALID then VALIDATE. Never edit a migration once applied.
"""

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    ${downgrades if downgrades else "pass"}
