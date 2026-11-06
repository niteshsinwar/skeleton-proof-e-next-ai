#!/usr/bin/env python3
"""Post-deploy smoke lane (06/T1, 07/O3): read-only checks against a deployed environment. `make smoke BASE_URL=...`.

Never writes: production is read-only to tools and agents (README #14), so every request is a GET and the only
journey is one that must be refused without credentials. Stdlib only: it runs on a bare runner, the host, or a laptop,
and scripts/deploy.py runs it after every deploy and rollback, reverting when it fails (07/O6).

  python3 -I tests/smoke/smoke.py --base-url https://api.example.com --web-url https://app.example.com [--sha <40 hex>]

The base URL is the API's; the web URL is the Next.js app's.
Not a test module (12/N5): the unit lane tests these checks both ways (apps/api/tests/unit/test_smoke.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

API_PREFIX = ""
UI = "next"
SHA = re.compile(r"^[0-9a-f]{7,40}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None  # a redirect is an answer to check, never a hop to another host


OPENER = urllib.request.build_opener(NoRedirect)


TRIES = 3


def get(url: str) -> tuple[int, dict[str, str], bytes]:
    """GET only, by construction; an HTTP error status is a result. Connection errors are retried briefly."""
    tries = TRIES
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json, text/html"})  # noqa: S310
    for attempt in range(tries):
        try:
            with OPENER.open(request, timeout=10) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except urllib.error.HTTPError as error:
            return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()
        except urllib.error.URLError, ConnectionError, TimeoutError:
            if attempt == tries - 1:
                raise
            time.sleep(1)
    raise AssertionError("unreachable")


def _json(body: bytes) -> dict[str, object]:
    try:
        found = json.loads(body)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def check_health(api: str, sha: str | None) -> str | None:
    status, _, body = get(f"{api}/health")
    shown = str(_json(body).get("sha", ""))
    if status != 200:
        return f"/health answered {status}"
    if sha and shown != sha:
        return f"/health shows {shown!r}, expected the deployed {sha!r}: the wrong build is serving (02/A12)"
    if not SHA.match(shown):
        return f"/health shows {shown!r}, not a git SHA (02/A12)"
    return None


def check_ready(api: str) -> str | None:
    status, _, body = get(f"{api}/ready")
    if status != 200:
        return f"/ready answered {status}: {_json(body).get('checks', body[:200])}"
    return None


def check_auth_wall(api: str) -> str | None:
    """The one read journey a tool may take in production: an anonymous read must be refused (02/Z1)."""
    status, headers, _ = get(f"{api}/work-items")
    if status != 401:
        return f"an anonymous GET /work-items answered {status}, not 401: the API is not refusing strangers"
    if not headers.get("content-type", "").startswith("application/problem+json"):
        return "the 401 is not a problem+json body (02/A4)"
    return None


def check_web_root(web: str) -> str | None:
    """The app's page carries its Content-Security-Policy; scripts never run inline (03/F38)."""
    status, headers, _ = get(f"{web}/")
    csp = headers.get("content-security-policy", "")
    script_src = csp.split("script-src", 1)[1].split(";", 1)[0] if "script-src" in csp else ""
    if status >= 500:
        return f"the web root answered {status}"
    if not script_src:
        return f"the web root sends no script-src in its CSP: {csp!r}"
    if "'unsafe-inline'" in script_src:
        return f"the CSP allows inline scripts: {script_src.strip()!r}"
    if headers.get("x-content-type-options") != "nosniff":
        return "the web root lacks X-Content-Type-Options: nosniff"
    return None


def checks(base_url: str, sha: str | None, web_url: str | None = None) -> list[tuple[str, Callable[[], str | None]]]:
    api = base_url.rstrip("/") + API_PREFIX
    found: list[tuple[str, Callable[[], str | None]]] = [
        ("health shows the deployed build", lambda: check_health(api, sha)),
        ("ready: database, migration head, configuration", lambda: check_ready(api)),
        ("an anonymous read is refused", lambda: check_auth_wall(api)),
    ]
    if not web_url:
        raise SystemExit("smoke: --web-url is required: this project has a web app")
    found.append(("the app's page and its CSP", lambda: check_web_root(web_url.rstrip("/"))))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--web-url")
    parser.add_argument("--sha", help="the git SHA that must be serving (deploys always pass it)")
    args = parser.parse_args(argv)
    if not args.base_url.startswith(("http://", "https://")):
        raise SystemExit("smoke: --base-url must be an http(s) URL")
    failed = 0
    found = checks(args.base_url, args.sha or None, args.web_url)
    for name, probe in found:
        try:
            problem = probe()
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            problem = f"unreachable: {error}"
        failed += problem is not None
        print(f"smoke: {'pass' if problem is None else 'FAIL'}  {name}" + (f": {problem}" if problem else ""))
    print(f"smoke: examined {len(found)} checks against {args.base_url}, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
