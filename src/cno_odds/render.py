"""Write docs/data.json and docs/index.html from the computed rows."""

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader

_DOCS = Path(__file__).parents[2] / "docs"
_TEMPLATES = Path(__file__).parent / "templates"
_EASTERN = ZoneInfo("America/New_York")


def _utc_to_et(utc_str: str) -> str:
    """Convert a UTC ISO-8601 string to a display string in Eastern Time.

    Returns e.g. '05/22 07:30 PM EDT'
    """
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        et = dt.astimezone(_EASTERN)
        abbr = "EDT" if et.dst() else "EST"
        return et.strftime(f"%m/%d %I:%M %p {abbr}").lstrip("0")
    except Exception:
        return utc_str[:16]


def render(rows: list[dict], cfg: dict) -> None:
    _DOCS.mkdir(exist_ok=True)

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(_EASTERN)
    abbr = "EDT" if now_et.dst() else "EST"
    generated_at = now_et.strftime(f"%Y-%m-%d %H:%M {abbr}")

    threshold = cfg["thresholds"]["hold_max_pct"]

    display_rows = [r for r in rows if r["hold_pct"] <= threshold]

    pre_game = [r for r in display_rows if not r.get("is_live")]
    live_rows = [r for r in display_rows if r.get("is_live")]

    qualified = [r for r in pre_game if r["qualified"]]
    unqualified = [r for r in pre_game if not r["qualified"]]

    data = {
        "generated_at": generated_at,
        "thresholds": cfg["thresholds"],
        "rows": display_rows,
    }
    (_DOCS / "data.json").write_text(json.dumps(data, indent=2))

    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=True)
    env.filters["to_et"] = _utc_to_et

    tmpl = env.get_template("index.html.j2")
    html = tmpl.render(
        generated_at=generated_at,
        thresholds=cfg["thresholds"],
        qualified=qualified,
        unqualified=unqualified,
        live_rows=live_rows,
    )
    (_DOCS / "index.html").write_text(html)

    print(
        f"Dashboard: {len(qualified)} qualified, {len(unqualified)} unqualified, "
        f"{len(live_rows)} live (hidden by default)."
    )
    print(f"Output: {_DOCS / 'index.html'}")
