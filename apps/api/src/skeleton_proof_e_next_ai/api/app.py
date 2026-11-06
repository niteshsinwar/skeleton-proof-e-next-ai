"""App factory (the composition root): wires settings, adapters and routers. Run with
`uvicorn <package>.api.app:create_app --factory`. No module-level app, so importing never connects.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI, Request, Response
from opentelemetry.trace import Tracer

from ..application import outside_tools
from ..application.proposals import PlainApprovalWorkflow
from ..config import production as deployed_config
from ..config.project import PROJECT_NAME, SERVICE
from ..config.settings import Settings, get_settings
from ..intelligence import agents as ai_agents
from ..intelligence import catalogue as ai_catalogue
from ..intelligence import mcp as outside_mcp
from ..intelligence.embeddings import Embeddings
from ..intelligence.gateway import Gateway
from ..intelligence.graphs.approval import LangGraphApprovalWorkflow
from ..intelligence.graphs.checkpoints import open_checkpointer
from ..intelligence.mcp import McpGateway
from ..intelligence.project_steps import REGISTRY
from ..intelligence.registry import check
from ..intelligence.steps import StepRunner
from ..intelligence.tools import TOOLS, ToolRegistry
from ..persistence import business_config
from ..persistence.db import Database
from ..persistence.files import LocalBlobStore
from ..persistence.mcp_connections import PgMcpConnections
from ..retrieval.engine import HybridRetriever
from ..security.rate_limit import MemoryRateLimiter, PostgresRateLimiter
from ..security.sealed import SecretBox
from ..telemetry import context, otel
from ..telemetry.logging import configure_logging
from . import deprecation, errors
from . import mcp as mcp_endpoint
from .auth import TokenVerifier
from .deps import AppState
from .proposal_kinds import EXECUTORS
from .routers import ai as ai_routes
from .routers import documents, mcp_connections, platform, proposals, webhooks, work_item_brief, work_items

log = logging.getLogger("access")


def build_ai(settings: Settings, tracer: Tracer | None = None) -> tuple[StepRunner, ai_catalogue.Catalogue, McpGateway]:
    """The product AI, checked at start: a wrong catalogue, agent file, pin or registry entry stops the app (02/B5).

    Providers are built only for credentials present in the environment; without one, AI runs off (01/R5).
    """
    now = datetime.now(UTC)
    production = settings.env == "production"
    catalogue = ai_catalogue.load(settings.ai_dir / "models.yaml", today=now.date(), production=production)
    agents = ai_agents.load_agents(settings.ai_dir / "agents", catalogue)
    # Outside MCP servers join the one tool registry, so agent files may list their tools (04/K3).
    outside = McpGateway(outside_mcp.load(settings.ai_dir / "mcp-servers.yaml", production=production))
    tools = ToolRegistry((*TOOLS, *outside_mcp.registry_tools(outside)))
    problems = ai_agents.check_pins(agents, settings.ai_dir / "agents" / "pins.json") + check(REGISTRY, agents, tools)
    if production and outside.servers() and settings.mcp_secrets_key is None:
        problems.append("outside MCP servers are configured but APP_MCP_SECRETS_KEY is not set")
    if problems:
        raise RuntimeError("the product AI is misconfigured: " + "; ".join(problems))
    gateway = Gateway.from_environment(catalogue, os.environ)
    return StepRunner(REGISTRY, agents, gateway, lambda: datetime.now(UTC), tracer=tracer), catalogue, outside


def observe_requests(app: FastAPI, telemetry: otel.Telemetry) -> None:
    """Every request: a correlation id (07/O7), a server span and a RED point by route template (07/O8)."""

    @app.middleware("http")
    async def correlate(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-request-id", "")
        cid = (
            incoming
            if 0 < len(incoming) <= 64 and incoming.replace("-", "").isalnum()
            else context.new_correlation_id()
        )
        token = context.correlation_id.set(cid)
        started = time.perf_counter()
        with telemetry.tracer.start_as_current_span(request.method, kind=otel.SERVER) as span:
            status = 500  # what a request that raises counts as
            try:
                response = await call_next(request)
                status = response.status_code
            finally:
                context.correlation_id.reset(token)
                # The route template, never the path: ids in paths would make every request its own series (07/O8).
                route = getattr(request.scope.get("route"), "path", "unmatched")
                otel.finish_request_span(span, request.method, route, status, cid)
                telemetry.record_request(time.perf_counter() - started, request.method, route, status)
        response.headers["X-Request-ID"] = cid
        log.info(
            "request",
            extra={
                "fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "correlation_id": cid,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                }
            },
        )
        return response


def create_app(settings: Settings | None = None, telemetry: otel.Telemetry | None = None) -> FastAPI:
    settings = settings or get_settings()
    telemetry = telemetry or otel.configure(f"{SERVICE}-api", settings.build_sha, settings.env, settings.otel_endpoint)
    configure_logging()
    unsafe = deployed_config.problems(settings)
    if unsafe:  # fail closed: a deployed API never starts on a development setting (07/O4, README #6)
        raise RuntimeError(f"refusing to start in {settings.env}: " + "; ".join(unsafe))
    db = Database(settings.database_url, settings.db_app_role, settings.db_worker_role, settings.db_pool_size)
    limiter = (
        PostgresRateLimiter(db.engine, settings.db_app_role)
        if settings.rate_limit_store == "postgres"
        else MemoryRateLimiter()
    )
    runner, catalogue, outside = build_ai(settings, telemetry.tracer)

    secret = settings.mcp_secrets_key
    mcp_box = SecretBox.from_setting(secret.get_secret_value() if secret is not None else None)

    async def run_approved(proposal_id: UUID, decided_by: str, tenant_id: UUID) -> None:
        await proposals.run_approved(core, proposal_id, decided_by, tenant_id)

    core = AppState(
        settings=settings,
        db=db,
        limiter=limiter,
        blobs=LocalBlobStore(settings.upload_dir),
        verifier=TokenVerifier.from_file(
            settings.auth_jwks_file,
            settings.auth_issuer,
            settings.auth_audience,
            settings.auth_algorithms,
            tenant_claim=settings.auth_tenant_claim,
            strong_amr=settings.auth_strong_amr,
            step_up_seconds=settings.auth_step_up_seconds,
        ),
        mcp_verifier=TokenVerifier.from_file(
            settings.auth_jwks_file,
            settings.auth_issuer,
            settings.mcp_audience,
            settings.auth_algorithms,
            tenant_claim=settings.auth_tenant_claim,
            strong_amr=settings.auth_strong_amr,
            step_up_seconds=settings.auth_step_up_seconds,
        ),
        business=business_config.load(settings.business_config_dir),  # invalid config fails at start (02/B5)
        ai=runner,
        ai_daily_cap_usd=catalogue.limits.tenant_daily_usd,
        ai_workflow=PlainApprovalWorkflow(run_approved),
        ai_executors={
            **EXECUTORS,
            outside_tools.PROPOSAL_KIND: lambda conn: outside_tools.OutsideToolExecutor(
                outside, PgMcpConnections(conn, mcp_box)
            ),
        },
        mcp_tools=outside,
        mcp_box=mcp_box,
        retriever=HybridRetriever(Embeddings.from_environment(catalogue, os.environ)),
    )

    mcp_server = mcp_endpoint.build(core)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_server.session_manager.run())
            if settings.ai_workflow == "langgraph":
                saver = await stack.enter_async_context(open_checkpointer(settings.database_url, settings.db_app_role))
                core.ai_workflow = LangGraphApprovalWorkflow(saver, run_approved)
            yield
        await db.dispose()
        telemetry.shutdown()  # flushes what is buffered for the exporter

    app = FastAPI(title=f"{PROJECT_NAME} API", version="0.1.0", lifespan=lifespan)
    app.state.core = core

    observe_requests(app, telemetry)

    errors.install(app)
    deprecation.install(app)  # a retiring route's Deprecation and Sunset headers (02/A10)
    app.include_router(platform.router)
    app.include_router(work_items.router)
    app.include_router(ai_routes.router)
    app.include_router(proposals.router)
    app.include_router(work_item_brief.router)  # EXAMPLE SLICE
    app.include_router(documents.router)
    app.include_router(mcp_connections.router)
    mcp_endpoint.mount(app, mcp_server, settings)  # after the API's routes, at the paths the MCP spec fixes
    app.include_router(webhooks.router)
    return app
