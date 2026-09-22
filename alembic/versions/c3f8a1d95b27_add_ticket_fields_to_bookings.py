"""add ticket fields to bookings

Revision ID: c3f8a1d95b27
Revises: 7cef2a1b2ec4
Create Date: 2026-09-21 12:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3f8a1d95b27'
down_revision: Union[str, Sequence[str], None] = '7cef2a1b2ec4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ticket_status_enum = postgresql.ENUM(
    'pending', 'sent', 'failed', name='ticketstatus', create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM('pending', 'sent', 'failed', name='ticketstatus').create(bind, checkfirst=True)

    # ticket_code starts nullable so existing rows can be backfilled, then becomes NOT NULL
    op.add_column('bookings', sa.Column('ticket_code', sa.String(length=36), nullable=True))
    op.add_column('bookings', sa.Column(
        'ticket_status', ticket_status_enum, server_default='pending', nullable=False))
    op.add_column('bookings', sa.Column('ticket_queued_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('ticket_sent_at', sa.DateTime(timezone=True), nullable=True))

    # Backfill: every existing booking gets a unique code...
    for (booking_id,) in bind.execute(sa.text("SELECT id FROM bookings")).fetchall():
        bind.execute(
            sa.text("UPDATE bookings SET ticket_code = :code WHERE id = :id"),
            {"code": str(uuid.uuid4()), "id": booking_id},
        )
    # ...and is marked 'sent' so the sweeper doesn't email tickets for old (pre-feature)
    # bookings. Users can still download them via GET /bookings/{id}/ticket.
    op.execute("UPDATE bookings SET ticket_status = 'sent'")

    op.alter_column('bookings', 'ticket_code', existing_type=sa.String(length=36), nullable=False)
    op.create_index(op.f('ix_bookings_ticket_code'), 'bookings', ['ticket_code'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_bookings_ticket_code'), table_name='bookings')
    op.drop_column('bookings', 'ticket_sent_at')
    op.drop_column('bookings', 'ticket_queued_at')
    op.drop_column('bookings', 'ticket_status')
    op.drop_column('bookings', 'ticket_code')
    postgresql.ENUM(name='ticketstatus').drop(op.get_bind(), checkfirst=True)