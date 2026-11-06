"""Run the worker: the outbox relay, the job loop and the reaper (02/J2, 02/J3). `make worker`.

Without this nothing would ever run a job outside the tests: built is not reachable (10/H18). SIGTERM (what a
container platform sends) or Ctrl-C drains it: the job in hand finishes, nothing new is claimed (07/O6). A job cut
off by a hard kill is reaped after its visibility timeout and runs again under its idempotency key.
"""

from __future__ import annotations

import os
import signal
import socket

import anyio

from ..config.project import SERVICE
from ..config.settings import get_settings
from ..persistence.db import Database
from ..telemetry import otel
from ..telemetry.logging import configure_logging
from .worker import run_forever


async def serve(db: Database, name: str, telemetry: otel.Telemetry) -> None:
    stop = anyio.Event()

    async def on_signal() -> None:
        with anyio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signals:
            async for _ in signals:
                stop.set()
                return

    async with anyio.create_task_group() as tg:
        tg.start_soon(on_signal)
        await run_forever(db, name, stop=stop, tracer=telemetry.tracer)
        tg.cancel_scope.cancel()
    await db.dispose()
    telemetry.shutdown()


def main() -> None:
    settings = get_settings()
    configure_logging()
    db = Database(settings.database_url, settings.db_app_role, settings.db_worker_role, settings.db_pool_size)
    telemetry = otel.configure(f"{SERVICE}-worker", settings.build_sha, settings.env, settings.otel_endpoint)
    anyio.run(serve, db, f"{socket.gethostname()}-{os.getpid()}", telemetry)


if __name__ == "__main__":
    main()
