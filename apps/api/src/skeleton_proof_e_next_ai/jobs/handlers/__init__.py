"""Job handlers, one module per area. Every module here registers at least one handler (02/B4, tested)."""

from . import (
    webhooks,  # noqa: F401
    work_items,  # noqa: F401
)

MODULES = ["work_items", "webhooks"]
