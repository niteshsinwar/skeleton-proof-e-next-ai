"""Eval suite options and fixtures (06 §2)."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--runs", type=int, default=3, help="repetitions per case; a live eval needs at least 3 (06/E4)")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
