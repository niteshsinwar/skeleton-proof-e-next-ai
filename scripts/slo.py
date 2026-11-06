#!/usr/bin/env python3
"""SLOs as code: load ops/slo/*.yaml strictly and generate burn-rate alerts from them (07/O13-O15, OL2, OL3).

  python3 -I scripts/slo.py check                 # validate every SLO file; list owners still OPEN
  python3 -I scripts/slo.py alerts [--out FILE]   # Prometheus rules; refuses an OPEN owner
  python3 -I scripts/slo.py alerts --allow-open-owners   # preview before owners are named

Standard library only, so the files are read by a strict subset of YAML: block mappings and lists, comments, plain or
quoted scalars. Anchors, flow collections, multi-line strings, tabs and duplicate keys are refused, as is any key
the schema doesn't know, a route that isn't 'METHOD /path', a target outside (0, 100) or too low for its alerts ever
to fire, a latency threshold that is not a histogram bucket, an objective without an owner, and a runbook link to a
file or heading that doesn't exist.

The alerts follow the multiwindow, multi-burn-rate method (Google SRE Workbook, "Alerting on SLOs"): page when 2% of
the budget burns in 1 h or 5% in 6 h, each confirmed over a window 1/12 as long; open a ticket when 10% burns in
3 days. "System down" (availability, latency) and "AI quality degraded" (quality) are separate alerts with their own
owners and runbooks (07/O15). The output is Prometheus rule YAML, one option among several: the burn-rate maths in
`burn_thresholds` is vendor-neutral, and wiring the alerts into another monitoring system is the project's.

Exit 0 = pass; 1 = a problem (each printed with its file and line); 2 = usage.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_OWNER = "@OWNER"  # docs/open-questions.md: an owner nobody has named yet

# What the alert expressions read. OpenTelemetry's HTTP server histogram `http.server.request.duration` (seconds), as
# Prometheus names it after the standard translation; the quality counter is emitted by the project's sampled online
# grading or eval runs (one increment per judged answer, verdict "pass" or "fail").
HTTP_METRIC = "http_server_request_duration_seconds"
QUALITY_METRIC = "ai_quality_judgements_total"
# OpenTelemetry's default bucket boundaries for http.server.request.duration, in milliseconds. A latency threshold
# must be one of them, or the `le` selector matches no series and the SLI reads as 100% bad.
BUCKETS_MS = (5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000)

# (severity, share of the budget, long window in hours, short window in hours): 07/O14, W37.
POLICY = (
    ("page", 0.02, 1, 1 / 12),
    ("page", 0.05, 6, 0.5),
    ("ticket", 0.10, 72, 6),
)
OBJECTIVES = {"availability", "latency", "quality"}
CLASS = {"availability": "system", "latency": "system", "quality": "ai-quality"}
ALERT_NAME = {"availability": "SystemDown", "latency": "SystemSlow", "quality": "AIQualityDegraded"}


class SLOError(Exception):
    """A file that breaks the schema or the YAML subset; the message names the file and line."""


# --- the strict YAML subset -------------------------------------------------------------------------------------


@dataclass
class Node:
    value: object
    line: int


def _scalar(raw: str, where: str) -> object:
    if raw[:1] in "\"'":
        quote = raw[0]
        if len(raw) < 2 or raw[-1] != quote or quote in raw[1:-1]:
            raise SLOError(f"{where}: unbalanced or nested quotes in {raw!r}")
        return raw[1:-1]
    if raw[:1] in "&*!|>{[%@`":
        raise SLOError(f"{where}: {raw[:1]!r} starts YAML outside the subset this loader accepts (quote the value)")
    if raw in ("true", "false"):
        return raw == "true"
    if raw in ("null", "~", "yes", "no", "on", "off"):
        raise SLOError(f"{where}: {raw!r} is ambiguous YAML; write true, false or a quoted string")
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def _strip_comment(text: str) -> str:
    quote = None
    for i, ch in enumerate(text):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] == " "):
            return text[:i].rstrip()
    return text.rstrip()


def parse(text: str, name: str) -> Node:
    """Parse the subset into Node trees (dicts and lists of Nodes), keeping line numbers for every message."""
    lines: list[tuple[int, int, str]] = []
    for no, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw:
            raise SLOError(f"{name}:{no}: a tab; indent with two spaces")
        body = _strip_comment(raw)
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip(" "))
        if indent % 2:
            raise SLOError(f"{name}:{no}: indentation must be a multiple of two spaces")
        if body.strip() in ("---", "..."):
            raise SLOError(f"{name}:{no}: one document per file, without '---'")
        lines.append((no, indent, body.strip()))
    if not lines:
        raise SLOError(f"{name}: the file is empty")
    node, rest = _block(lines, 0, name)
    if rest:
        raise SLOError(f"{name}:{lines[-len(rest)][0]}: unexpected indentation")
    return node


def _block(lines: list[tuple[int, int, str]], indent: int, name: str) -> tuple[Node, list[tuple[int, int, str]]]:
    first_no, first_indent, first = lines[0]
    if first_indent != indent:
        raise SLOError(f"{name}:{first_no}: expected indentation {indent}, found {first_indent}")
    if first.startswith("- ") or first == "-":
        items: list[Node] = []
        while lines and lines[0][1] == indent and lines[0][2].startswith("-"):
            no, _, text = lines.pop(0)
            item = text[1:].strip()
            if not item or re.match(r"^[A-Za-z_][\w-]*:(\s|$)", item):
                raise SLOError(f"{name}:{no}: list items are plain values here, not mappings")
            items.append(Node(_scalar(item, f"{name}:{no}"), no))
        return Node(items, first_no), lines
    mapping: dict[str, Node] = {}
    while lines and lines[0][1] == indent:
        no, _, text = lines.pop(0)
        m = re.fullmatch(r"([A-Za-z_][\w-]*):(?:\s+(.*))?", text)
        if not m:
            raise SLOError(f"{name}:{no}: expected `key: value`, found {text!r}")
        key, raw = m.group(1), m.group(2)
        if key in mapping:
            raise SLOError(f"{name}:{no}: duplicate key {key!r}")
        if raw:
            mapping[key] = Node(_scalar(raw, f"{name}:{no}"), no)
        elif lines and lines[0][1] > indent:
            mapping[key], lines = _block(lines, indent + 2, name)
        else:
            raise SLOError(f"{name}:{no}: {key!r} has no value")
    if lines and lines[0][1] > indent:
        raise SLOError(f"{name}:{lines[0][0]}: unexpected indentation")
    return Node(mapping, first_no), lines


# --- the schema ---------------------------------------------------------------------------------------------------


@dataclass
class Objective:
    kind: str
    target: float  # percent of good events in the window, e.g. 99.5
    owner: str
    runbook: str
    threshold_ms: int | None = None  # latency
    step: str | None = None  # quality: the AI step whose judged answers count


@dataclass
class Journey:
    name: str
    title: str
    starter: bool
    measured: str | None
    window_days: int
    routes: list[tuple[str, str]]
    objectives: list[Objective] = field(default_factory=list)
    source: str = ""


JOURNEY_KEYS = {"journey": True, "title": True, "starter": True, "measured": False, "window_days": True,
                "routes": True, "objectives": True}
OBJECTIVE_KEYS = {
    "availability": {"target", "owner", "runbook"},
    "latency": {"target", "owner", "runbook", "threshold_ms"},
    "quality": {"target", "owner", "runbook", "step"},
}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _keys(node: Node, allowed: set[str], required: set[str], where: str) -> dict[str, Node]:
    if not isinstance(node.value, dict):
        raise SLOError(f"{where}:{node.line}: expected a mapping")
    found: dict[str, Node] = node.value
    for key, child in found.items():
        if key not in allowed:
            raise SLOError(f"{where}:{child.line}: unknown key {key!r} (allowed: {', '.join(sorted(allowed))})")
    missing = sorted(required - set(found))
    if missing:
        raise SLOError(f"{where}:{node.line}: missing {', '.join(missing)}")
    return found


def _typed(node: Node, kind: type | tuple[type, ...], where: str, what: str) -> object:
    if isinstance(node.value, bool) and kind is not bool:
        raise SLOError(f"{where}:{node.line}: {what} must not be true or false")
    if not isinstance(node.value, kind):
        raise SLOError(f"{where}:{node.line}: {what} has the wrong type ({type(node.value).__name__})")
    return node.value


def runbook_problem(link: str, root: Path) -> str | None:
    """A runbook link is `path` or `path#heading-slug`, relative to the project root; both must exist."""
    path, _, anchor = link.partition("#")
    file = root / path
    if not path.startswith("ops/runbooks/") or not file.is_file():
        return f"runbook {link!r} is not a file under ops/runbooks/"
    if anchor:
        slugs = {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", file.read_text(), re.M)}
        if anchor not in slugs:
            return f"runbook {link!r}: {path} has no heading with the anchor #{anchor}"
    return None


def slug(heading: str) -> str:
    """GitHub's heading anchors: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


def load_journey(path: Path, root: Path = ROOT) -> Journey:
    name = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
    top = _keys(parse(path.read_text(encoding="utf-8"), name), set(JOURNEY_KEYS),
                {k for k, req in JOURNEY_KEYS.items() if req}, name)
    journey = str(_typed(top["journey"], str, name, "journey"))
    if journey != path.stem or not re.fullmatch(r"[a-z][a-z0-9-]*", journey):
        raise SLOError(f"{name}:{top['journey'].line}: journey must be lowercase-with-hyphens and match the file name")
    starter = bool(_typed(top["starter"], bool, name, "starter"))
    measured = top.get("measured")
    if starter and measured is not None:
        raise SLOError(f"{name}:{measured.line}: a starter has no measured date; set starter: false when measured")
    if not starter and (measured is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(measured.value))):
        raise SLOError(f"{name}:{top['starter'].line}: starter: false needs `measured: YYYY-MM-DD` (01/R1)")
    window = int(_typed(top["window_days"], int, name, "window_days"))
    if not 7 <= window <= 90:
        raise SLOError(f"{name}:{top['window_days'].line}: window_days must be between 7 and 90")
    routes: list[tuple[str, str]] = []
    for item in _typed(top["routes"], list, name, "routes"):
        m = re.fullmatch(r"([A-Z]+) (/[\w/{}.-]*)", str(item.value))
        if not m or m.group(1) not in METHODS:
            raise SLOError(f"{name}:{item.line}: a route is 'METHOD /path', e.g. 'GET /work-items'")
        routes.append((m.group(1), m.group(2)))
    objectives = _keys(top["objectives"], OBJECTIVES, {"availability"}, name)
    out = Journey(journey, str(_typed(top["title"], str, name, "title")), starter,
                  str(measured.value) if measured else None, window, routes, source=name)
    for kind, node in objectives.items():
        keys = _keys(node, OBJECTIVE_KEYS[kind], OBJECTIVE_KEYS[kind], name)
        target = float(_typed(keys["target"], (int, float), name, "target"))
        if not 0 < target < 100:
            raise SLOError(f"{name}:{keys['target'].line}: target is a percentage strictly between 0 and 100")
        owner = str(_typed(keys["owner"], str, name, "owner")).strip()
        if not owner:
            raise SLOError(f"{name}:{keys['owner'].line}: every alert has an owner (07/O15)")
        link = str(_typed(keys["runbook"], str, name, "runbook")).strip()
        problem = runbook_problem(link, root) if link else "every alert links a runbook (07/O15)"
        if problem:
            raise SLOError(f"{name}:{keys['runbook'].line}: {problem}")
        rows = burn_thresholds(target, window)
        never = [f"{sev} over {duration(long_h)}" for sev, _, long_h, _, limit in rows if limit >= 1]
        if never:
            raise SLOError(f"{name}:{keys['target'].line}: at {_num(target)}% the {', '.join(never)} alert needs an error "
                           "ratio above 1, so it can never fire; raise the target or change the policy (07/O14)")
        obj = Objective(kind, target, owner, link)
        if kind == "latency":
            obj.threshold_ms = int(_typed(keys["threshold_ms"], int, name, "threshold_ms"))
            if obj.threshold_ms not in BUCKETS_MS:
                raise SLOError(f"{name}:{keys['threshold_ms'].line}: threshold_ms must be a histogram bucket boundary "
                               f"({', '.join(map(str, BUCKETS_MS))})")
        if kind == "quality":
            obj.step = str(_typed(keys["step"], str, name, "step"))
        out.objectives.append(obj)
    return out


def load_all(folder: Path, root: Path = ROOT) -> list[Journey]:
    files = sorted(folder.glob("*.yaml"))
    if not files:
        raise SLOError(f"{folder}: no SLO files; an SLO per user-facing journey (07/O13)")
    return [load_journey(p, root) for p in files]


# --- burn-rate maths ----------------------------------------------------------------------------------------------


def budget(target: float) -> float:
    """The error budget as a ratio: 99.5% good leaves 0.005 to spend."""
    return round(1 - target / 100, 12)


def burn_rate(share: float, long_hours: float, window_days: int) -> float:
    """How many times faster than 'exactly on budget' the errors must arrive to spend `share` of it in `long_hours`."""
    return round(share * window_days * 24 / long_hours, 12)


def burn_thresholds(target: float, window_days: int) -> list[tuple[str, float, float, float, float]]:
    """(severity, burn rate, long window h, short window h, error-ratio threshold) per POLICY row."""
    return [(sev, burn_rate(share, long_h, window_days), long_h, short_h,
             round(burn_rate(share, long_h, window_days) * budget(target), 12))
            for sev, share, long_h, short_h in POLICY]


def duration(hours: float) -> str:
    minutes = round(hours * 60)
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)}d"
    return f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"


# --- Prometheus rules ---------------------------------------------------------------------------------------------


def _num(x: float) -> str:
    return format(x, ".10g")


def _routes_selector(routes: list[tuple[str, str]], extra: str = "") -> list[str]:
    by_method: dict[str, list[str]] = {}
    for method, path in routes:
        by_method.setdefault(method, []).append(re.escape(path).replace("\\", "\\\\").replace('"', '\\"'))
    return [f'http_request_method="{m}",http_route=~"^({"|".join(paths)})$"{extra}'
            for m, paths in sorted(by_method.items())]


def _sum(metric: str, selectors: list[str], window: str) -> str:
    return "sum(" + " or ".join(f"rate({metric}{{{s}}}[{window}])" for s in selectors) + ")"


def error_ratio(journey: Journey, obj: Objective, window: str) -> str:
    if obj.kind == "availability":
        bad = _sum(f"{HTTP_METRIC}_count", _routes_selector(journey.routes, ',http_response_status_code=~"5.."'), window)
        return f"({bad} or vector(0)) / {_sum(f'{HTTP_METRIC}_count', _routes_selector(journey.routes), window)}"
    if obj.kind == "latency":
        assert obj.threshold_ms is not None
        seconds = obj.threshold_ms / 1000
        le = f'le=~"{int(seconds)}(\\\\.0)?"' if seconds == int(seconds) else f'le="{_num(seconds)}"'
        fast = _sum(f"{HTTP_METRIC}_bucket", _routes_selector(journey.routes, f",{le}"), window)
        return f"1 - ({fast} / {_sum(f'{HTTP_METRIC}_count', _routes_selector(journey.routes), window)})"
    sel = f'step="{obj.step}"'
    bad = f'sum(rate({QUALITY_METRIC}{{{sel},verdict="fail"}}[{window}]))'
    return f"({bad} or vector(0)) / sum(rate({QUALITY_METRIC}{{{sel}}}[{window}]))"


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-"))


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def prometheus_rules(journeys: list[Journey]) -> str:
    out = [
        "# Generated by scripts/slo.py from ops/slo/*.yaml: edit those, never this file (07/O13-O15).",
        "# Prometheus rule format, one option among several; the burn-rate policy is vendor-neutral (ops/slo/README.md).",
        "groups:",
    ]
    for j in journeys:
        for obj in j.objectives:
            labels = f'journey="{j.name}",objective="{obj.kind}"'
            rows = burn_thresholds(obj.target, j.window_days)
            windows = sorted({w for _, _, long_h, short_h, _ in rows for w in (long_h, short_h)})
            out += [f"  - name: slo-{j.name}-{obj.kind}", "    rules:"]
            for w in windows:
                out += [f"      - record: slo:sli_error:ratio_rate{duration(w)}",
                        f"        expr: {_q(error_ratio(j, obj, duration(w)))}",
                        "        labels:", f"          journey: {j.name}", f"          objective: {obj.kind}"]
            for severity in ("page", "ticket"):
                clauses = [
                    f"(slo:sli_error:ratio_rate{duration(long_h)}{{{labels}}} > {_num(threshold)} and "
                    f"slo:sli_error:ratio_rate{duration(short_h)}{{{labels}}} > {_num(threshold)})"
                    for sev, _, long_h, short_h, threshold in rows if sev == severity
                ]
                spent = ", ".join(f"{_num(share * 100)}% of the budget in {duration(long_h)}"
                                  for sev, share, long_h, _ in POLICY if sev == severity)
                out += [
                    f"      - alert: {_camel(j.name)}{ALERT_NAME[obj.kind]}{severity.capitalize()}",
                    f"        expr: {_q(' or '.join(clauses))}",
                    "        labels:",
                    f"          severity: {severity}",
                    f"          alert_class: {CLASS[obj.kind]}",
                    f"          owner: {_q(obj.owner)}",
                    f"          journey: {j.name}",
                    f"          objective: {obj.kind}",
                    "        annotations:",
                    f"          summary: {_q(f'{j.title}: {obj.kind} SLO ({_num(obj.target)}%) burning fast: {spent}')}",
                    f"          runbook: {_q(obj.runbook)}",
                ]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "alerts"])
    parser.add_argument("--dir", type=Path, default=ROOT / "ops" / "slo")
    parser.add_argument("--root", type=Path, default=ROOT, help="where runbook links are resolved")
    parser.add_argument("--out", type=Path, help="write the alert rules here instead of printing them")
    parser.add_argument("--allow-open-owners", action="store_true", help="preview alerts before owners are named")
    args = parser.parse_args(argv[1:])
    # Printed rules own stdout, so the summary goes to stderr; with --out (or `check`) everything is on stdout.
    log = sys.stderr if args.command == "alerts" and not args.out else sys.stdout
    try:
        journeys = load_all(args.dir, args.root)
    except SLOError as err:
        print(f"slo: FAIL: {err}", file=log)
        return 1
    objectives = [(j, o) for j in journeys for o in j.objectives]
    print(f"slo: examined {len(journeys)} journeys, {len(objectives)} objectives, "
          f"{sum(1 for j in journeys if j.starter)} still starters (01/R1)", file=log)
    open_owners = [f"{j.source}: {o.kind}" for j, o in objectives if o.owner == PLACEHOLDER_OWNER]
    for item in open_owners:
        print(f"  OPEN  owner {PLACEHOLDER_OWNER} for {item} (docs/open-questions.md)", file=log)
    if args.command == "check":
        print("slo: pass")
        return 0
    if open_owners and not args.allow_open_owners:
        print(f"slo: FAIL: {len(open_owners)} alert(s) have no named owner; an alert nobody owns is not shipped (07/O15)",
              file=log)
        return 1
    rules = prometheus_rules(journeys)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rules)
        print(f"slo: wrote {len(objectives) * 2} alerts to {args.out}")
    else:
        sys.stdout.write(rules)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
