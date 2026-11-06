"""Validation and verification of model output (04/Q4–Q5, 04/P6; Aegis B10).

The provider constrains its output to a JSON Schema, and the application validates it again, because a schema is a
floor, not an assurance. Then generic verifiers run, and any failure rejects the whole output; nothing is repaired:

- **Citations:** every `Citation` names a data block the model was shown and quotes it **verbatim**. A real block with
  a quote from elsewhere (misattribution) is caught here, and only here.
- **Links:** a URL in any string must point at a host the agent file allowlists (OWASP LLM05: no exfiltration links).
- **Abstention:** an output that abstains is recorded as an abstention, never as agreement (04/Q5).

A step adds its own verifiers for its domain (e.g. "a judgement no verified claim supports is an abstention").
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .ledger import Ledger

# Constraints the provider's structured output doesn't enforce; they are removed from the schema it sees and still
# checked here by Pydantic, which validates against the full model.
UNENFORCED = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
              "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties"}  # fmt: skip
URL = re.compile(r"https?://[^\s)\]>\"']+", re.I)
MIN_QUOTE = 8  # a quote shorter than this proves little; quote the whole block if it is shorter


class StepOutput(BaseModel):
    """Every step's output extends this. `abstain` is how the model says "I cannot", with its reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    abstain: str | None = Field(default=None, description="Fill this, and nothing else, when you cannot answer.")


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(description='The id of the data block, e.g. "c1".')
    quote: str = Field(description="The exact words from that block, copied character for character.")


Verifier = Callable[[StepOutput, Ledger], str | None]  # returns a stable reason code to reject, or None


def provider_schema(model: type[StepOutput]) -> dict[str, Any]:
    """The JSON Schema the provider constrains its output to: every object closed, unenforced constraints removed."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in UNENFORCED & node.keys():
                del node[key]
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


def parse(text: str, model: type[StepOutput]) -> tuple[StepOutput | None, str | None]:
    """Strict parse. Returns the output or a stable reason code; never a repaired object."""
    try:
        return model.model_validate(json.loads(text)), None
    except json.JSONDecodeError:
        return None, "not_json"
    except ValidationError:
        return None, "schema_violation"


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _walk(getattr(value, name))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)


def citations_verified(output: StepOutput, ledger: Ledger) -> str | None:
    for node in _walk(output):
        if isinstance(node, Citation):
            shown = ledger.text_of(node.source)
            if shown is None:
                return "citation_unknown_source"
            if node.quote not in shown or (len(node.quote) < MIN_QUOTE and node.quote != shown):
                return "citation_not_verbatim"
    return None


def links_allowed(allowed: list[str]) -> Verifier:
    hosts = {h.lower() for h in allowed}

    def verify(output: StepOutput, _: Ledger) -> str | None:
        for node in _walk(output):
            if isinstance(node, str):
                for url in URL.findall(node):
                    if (urlsplit(url).hostname or "").lower() not in hosts:
                        return "unsafe_link"
        return None

    return verify
