"""The model catalogue, `ai/models.yaml`: providers, models and routes (01/C5, 04/M1–M2; plans/b4 D13).

Agent files name a **route** (a kind of call: `default`, `fast`, `deep`, `judge`, or one the project adds), never a
model. A route names a model; a model names its provider. Switching a model or a provider is one line here, and each
kind of call can use its own model. A model change still re-runs the evals (04/M2).

The loader is strict (02/B5): an unknown key, provider, model or route, a model without a dated price, a retired model,
or a `judge` route on the family it grades is refused when the app starts, never discovered on a live call.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Effort = Literal["low", "medium", "high", "xhigh", "max"]


CHAT_ADAPTERS = frozenset({"anthropic", "fake"})
EMBEDDING_ADAPTERS = frozenset({"gemini", "fake"})


class CatalogueError(ValueError):
    """The catalogue is wrong. The app refuses to start rather than guess (02/B7)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provider(_Strict):
    # One adapter module per kind of provider (13/V7): adding a provider is one module and one row, by ADR.
    adapter: Literal["anthropic", "gemini", "fake"]
    credential_env: str | None = None  # the environment variable holding the credential; never the credential itself
    refusal_fallback: Literal["off", "default"] = "off"  # the provider's own retry on another model (plans/b4 D4)


class Price(_Strict):
    """US dollars per million tokens, as published on a date. Cost is computed from this, never estimated."""

    snapshot: str  # names the source and date, e.g. "anthropic-pricing-2026-10-06"
    input_per_mtok: Decimal = Field(ge=0)
    output_per_mtok: Decimal = Field(ge=0)
    cache_read_per_mtok: Decimal = Field(ge=0)
    cache_write_per_mtok: Decimal = Field(ge=0)


class Model(_Strict):
    provider: str
    id: str  # the provider's own model id, exactly as the provider spells it
    family: str  # used to keep a judge away from the family it grades (06/E5)
    price: Price
    retires_on: date | None = None


class Route(_Strict):
    model: str
    effort: Effort = "medium"
    max_output_tokens: int = Field(default=4000, ge=1, le=128_000)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    # Retries happen here, inside one budget, so retries can't multiply across layers (01/R6, 02/I2).
    max_attempts: int = Field(default=3, ge=1, le=5)


class EmbeddingPrice(_Strict):
    snapshot: str
    input_per_mtok: Decimal = Field(ge=0)


class EmbeddingModel(_Strict):
    """An embedding model at a fixed size. Changing either is a new embedding space, so a re-index (04/X4)."""

    provider: str
    id: str
    # The HNSW vector index covers up to 2000 dimensions; the stored column's size matches this number.
    dimensions: int = Field(ge=1, le=2000)
    max_input_tokens: int = Field(ge=1)  # the model's own limit; longer text is refused, never silently cut
    batch_size: int = Field(default=100, ge=1, le=250)
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_attempts: int = Field(default=3, ge=1, le=5)
    price: EmbeddingPrice
    retires_on: date | None = None

    @property
    def space(self) -> str:
        """The name stored with every vector: vectors from two spaces are never compared (04/X4)."""
        return f"{self.provider}/{self.id}@{self.dimensions}"


class Limits(_Strict):
    tenant_daily_usd: Decimal = Field(gt=0)  # cost units per tenant (01/R2); over it, calls are refused with 429


class Catalogue(_Strict):
    version: Literal[1]
    providers: dict[str, Provider]
    models: dict[str, Model]
    routes: dict[str, Route]
    embeddings: dict[str, EmbeddingModel] = Field(default_factory=dict)  # by use: `default`, or one the project adds
    limits: Limits

    @model_validator(mode="after")
    def _references_resolve(self) -> Catalogue:
        if "default" not in self.routes:
            raise ValueError("a `default` route is required")
        for name, model in self.models.items():
            if model.provider not in self.providers:
                raise ValueError(f"model {name!r} names unknown provider {model.provider!r}")
        for name, route in self.routes.items():
            if route.model not in self.models:
                raise ValueError(f"route {name!r} names unknown model {route.model!r}")
            if self.providers[self.models[route.model].provider].adapter not in CHAT_ADAPTERS:
                raise ValueError(f"route {name!r} uses a provider whose adapter can't answer messages")
        for name, embedding in self.embeddings.items():
            if embedding.provider not in self.providers:
                raise ValueError(f"embedding {name!r} names unknown provider {embedding.provider!r}")
            if self.providers[embedding.provider].adapter not in EMBEDDING_ADAPTERS:
                raise ValueError(f"embedding {name!r} uses a provider whose adapter can't embed")
        if "judge" in self.routes:
            judge = self.models[self.routes["judge"].model].family
            graded = {self.models[r.model].family for n, r in self.routes.items() if n != "judge"}
            if judge in graded:
                raise ValueError(
                    "the `judge` route must use a different model family from the routes it grades (06/E5)"
                )
        return self

    def route(self, name: str) -> Route:
        if name not in self.routes:
            raise CatalogueError(f"unknown route {name!r}; known: {', '.join(sorted(self.routes))}")
        return self.routes[name]

    def model_for(self, route: str) -> Model:
        return self.models[self.route(route).model]

    def provider_for(self, route: str) -> Provider:
        return self.providers[self.model_for(route).provider]


def load(path: Path, *, today: date, production: bool) -> Catalogue:
    """Read and check `ai/models.yaml`. Every problem is reported at once, so one start shows them all."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        catalogue = Catalogue.model_validate(raw)
    except FileNotFoundError as exc:
        raise CatalogueError(f"{path} is missing") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise CatalogueError(f"{path} is invalid: {exc}") from exc
    used = {catalogue.routes[r].model for r in catalogue.routes}
    retired = [m for m in sorted(used) if (d := catalogue.models[m].retires_on) is not None and d <= today]
    retired += [
        f"embedding {n}" for n, e in sorted(catalogue.embeddings.items()) if e.retires_on and e.retires_on <= today
    ]
    if retired:
        raise CatalogueError(f"routes use retired models: {', '.join(retired)} (07/O23)")
    if production:
        fakes = [n for n, p in catalogue.providers.items() if p.adapter == "fake"]
        if any(catalogue.models[catalogue.routes[r].model].provider in fakes for r in catalogue.routes) or any(
            e.provider in fakes for e in catalogue.embeddings.values()
        ):
            raise CatalogueError(
                "a route uses the fake provider in production (06/T4: a fake is never presented as real)"
            )
    return catalogue


def cost_usd(price: Price, *, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> Decimal:
    """Usage × the pinned rate (Aegis I §11 COMPUTED_LIVE_COST). Never an estimate."""
    per = Decimal(1_000_000)
    total = (
        price.input_per_mtok * input_tokens
        + price.output_per_mtok * output_tokens
        + price.cache_read_per_mtok * cache_read
        + price.cache_write_per_mtok * cache_write
    ) / per
    return total.quantize(Decimal("0.000001"))
