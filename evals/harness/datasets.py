"""Eval datasets: immutable releases at `evals/datasets/<name>/<version>/` (06/E3, 02/D16; Aegis B13).

A release is `cases.jsonl` plus `manifest.json`. The manifest pins the cases' SHA-256, so an edited release fails to
load: a change is a new version, built by its generator (`evals/generators/<name>.py`), never an edit. Each case says
what "good" means before its expected outcome (06/E1).

Refused at load: an edited release; an unknown layer or status; a one-sided set (06/E3: it must expect at least one
success and one other outcome); a matched pair that isn't exactly two cases; at tiers S and E, a set with no
injection case (05/SG5); and personal data: an email address outside the domains reserved for examples, or a
payment card number (05/SG8: eval sets carry no personal data, and synthetic data is labelled synthetic). The error
names the kind and the case, never the value. Secrets are gitleaks' job (`make secrets`), which scans evals/ too.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from skeleton_proof_e_next_ai.domain.ai import AttemptStatus, ContextItem, DataClass, StepInputs, Trust

Layer = Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6"]  # 06/E2: reported apart, never averaged
REQUIRE_ADVERSARIAL = True  # tier E


class DatasetError(ValueError):
    pass


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
# Domains reserved for documentation and tests (RFC 2606, RFC 6761): addresses there are synthetic by construction.
RESERVED = re.compile(r"(^|\.)(example\.(com|org|net)|example|test|invalid|localhost)$", re.I)
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def personal_data(text: str) -> list[str]:
    """The kinds of personal data found in a text (never the values themselves)."""
    kinds = []
    if any(not RESERVED.search(m.group(1)) for m in EMAIL.finditer(text)):
        kinds.append("an email address outside the reserved example domains")
    if any(_luhn(re.sub(r"[ -]", "", m.group(0))) for m in CARD.finditer(text)):
        kinds.append("a payment card number")
    return kinds


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseItem(_Strict):
    source: str
    ref: str
    text: str
    trust: Trust = Trust.RECORD
    data_class: DataClass = DataClass.INTERNAL
    stable: bool = False


class Inputs(_Strict):
    items: list[CaseItem]
    variables: dict[str, str] = {}


class Expect(_Strict):
    status: AttemptStatus
    must_include: list[str] = []  # phrases the verified result contains (case-insensitive)
    must_not_include: list[str] = []  # phrases neither the result nor the raw output may contain
    cites: list[str] = []  # data-block ids the result must cite
    max_cost_usd: float | None = None


class Case(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    layer: Layer
    tags: list[str] = Field(min_length=1)  # e.g. good, thin, absent, contradictory, injection_direct, held_out
    good: str = Field(min_length=1)  # what a good answer does, written before the expected outcome
    inputs: Inputs
    expect: Expect
    pair: str | None = None  # matched pairs (04/H3): two cases differing only in a protected or proxy attribute
    fixture: dict[str, Any] | None = None  # the scripted reply used ONLY by the harness self-test, never by an eval

    def step_inputs(self, tenant_id: Any, entity: str) -> StepInputs:
        items = tuple(
            ContextItem(i.source, i.ref, i.text, i.trust, tenant_id, i.data_class, stable=i.stable)
            for i in self.inputs.items
        )
        return StepInputs(items, dict(self.inputs.variables), entity, self.id)


class Manifest(_Strict):
    dataset: str
    version: int = Field(ge=1)
    step: str  # the registered step this release grades
    generator: str  # the one deterministic command that built it
    cases_sha256: str = Field(min_length=64, max_length=64)
    synthetic: bool  # synthetic data is labelled as synthetic (02/D16, 05/SG8)
    released: str


@dataclass(frozen=True)
class Dataset:
    manifest: Manifest
    cases: tuple[Case, ...]
    path: Path
    tags: dict[str, int] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.manifest.dataset}@{self.manifest.version}"


def _problems(cases: tuple[Case, ...], require_adversarial: bool) -> tuple[list[str], dict[str, int]]:
    """Everything that stops a release from measuring honestly, and the count of each tag."""
    problems: list[str] = []
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        problems.append("case ids repeat")
    expected = {c.expect.status for c in cases}
    if AttemptStatus.SUCCEEDED not in expected or expected == {AttemptStatus.SUCCEEDED}:
        problems.append("one-sided: expect at least one success and one other outcome (06/E3)")
    pairs: dict[str, list[Case]] = {}
    for c in cases:
        if c.pair:
            pairs.setdefault(c.pair, []).append(c)
    problems += [f"matched pair {p!r} has {len(m)} cases, not 2" for p, m in pairs.items() if len(m) != 2]
    split = [p for p, m in pairs.items() if len({x.expect.status for x in m}) > 1]
    problems += [f"matched pair {p!r} expects different outcomes" for p in split]
    tags: dict[str, int] = {}
    for c in cases:
        for t in c.tags:
            tags[t] = tags.get(t, 0) + 1
    for c in cases:
        problems += [f"case {c.id!r} holds {kind} (05/SG8)" for kind in personal_data(c.model_dump_json())]
    if require_adversarial and not any(t.startswith("injection_") for t in tags):
        problems.append("no injection case (tag injection_direct, injection_indirect or injection_encoded; 05/SG5)")
    return problems, tags


def load(path: Path, *, require_adversarial: bool = REQUIRE_ADVERSARIAL) -> Dataset:
    try:
        manifest = Manifest.model_validate_json((path / "manifest.json").read_text(encoding="utf-8"))
        raw = (path / "cases.jsonl").read_bytes()
    except (OSError, ValidationError) as exc:
        raise DatasetError(f"{path}: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != manifest.cases_sha256:
        raise DatasetError(f"{path}: cases.jsonl changed after release; build a new version with its generator")
    if path.name != f"v{manifest.version}" or path.parent.name != manifest.dataset:
        raise DatasetError(f"{path}: a release lives at {manifest.dataset}/v{manifest.version}/")
    try:
        cases = tuple(Case.model_validate(json.loads(line)) for line in raw.decode().splitlines() if line.strip())
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DatasetError(f"{path}: {exc}") from exc
    problems, tags = _problems(cases, require_adversarial)
    if problems:
        raise DatasetError(f"{path}: " + "; ".join(problems))
    return Dataset(manifest, cases, path, tags)


def release(path: Path, manifest: dict[str, Any], cases: list[dict[str, Any]]) -> Dataset:
    """What a generator calls: write a new release. An existing release is never overwritten (06/E3)."""
    if path.exists():
        raise DatasetError(f"{path} exists: releases are immutable; bump the version")
    path.mkdir(parents=True)
    body = "".join(json.dumps(c, sort_keys=True) + "\n" for c in cases).encode()
    (path / "cases.jsonl").write_bytes(body)
    (path / "manifest.json").write_text(
        json.dumps({**manifest, "cases_sha256": hashlib.sha256(body).hexdigest()}, indent=2, sort_keys=True) + "\n"
    )
    return load(path)


def all_releases(root: Path) -> list[Dataset]:
    return [load(p) for p in sorted(root.glob("*/v*")) if p.is_dir()]
