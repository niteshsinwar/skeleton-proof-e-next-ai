# Anthropic SDK and models (verified 2026-11-05)

What the gateway's Anthropic adapter relies on. Re-verify within 21 days of relying on it again (10/H17, H20).

| Fact | Status | Source |
|---|---|---|
| `anthropic` 2.3.0 is the newest release older than the 7-day cooldown (cutoff 2026-10-28); it runs on `httpx2` | READ | resolved with `uv lock` under `exclude-newer`; the installed package's `_version.py` |
| `AsyncAnthropic(api_key=..., max_retries=0)`. Without an explicit key the client looks for other credentials on the machine, so the adapter always passes one | READ | installed `anthropic/_client.py` |
| `messages.create(..., output_config={"effort": ..., "format": {"type": "json_schema", "schema": ...}})`; sampling parameters are no longer in the signature | READ | installed `anthropic/resources/messages/messages.py`, `types/output_config_param.py` |
| Refusal fallback: `beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`; the model that answered is `message.model` | READ | installed `resources/beta/messages/messages.py`, `types/beta/beta_fallbacks_param.py` |
| Stop reasons include `refusal` (with `stop_details.category`), `max_tokens` and `model_context_window_exceeded` | READ | installed `types/stop_reason.py`, `types/refusal_stop_details.py` |
| Usage reports `input_tokens`, `output_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` | READ | installed `types/usage.py` |
| Errors are typed (`RateLimitError`, `AuthenticationError`, `BadRequestError`, `OverloadedError`, `APITimeoutError`, …) | READ | installed `anthropic/_exceptions.py` |
| Structured outputs don't enforce `minLength`/`maxLength`, numeric or array-size constraints and need `additionalProperties: false` on every object; the app strips them from the schema it sends and validates them itself | RETRIEVED | the claude-api skill's tool-use reference (JSON Schema limitations) |
| Model ids and prices in `ai/models.yaml` (`claude-opus-5-5` $4 / $20, `claude-haiku-5-5` $0.10 / $0.50 per million tokens); cache rates derived from the standard multipliers | RETRIEVED | the claude-api skill's model table, cached 2026-10-06; check the provider's pricing page before relying on a cost |
