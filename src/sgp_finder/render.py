"""Write docs/sgp/data.json and docs/sgp/index.html.

Each run covers ONE sport; the renderer merges that sport's block into the
existing data.json so the dashboard keeps every sport's latest run and the
per-sport toggle stays client-side (no re-fetch). The workflow commits
docs/sgp back to main so cross-sport state survives between runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader

_DOCS = Path(__file__).parents[2] / "docs" / "sgp"
_TEMPLATES = Path(__file__).parent / "templates"
_EASTERN = ZoneInfo("America/New_York")


def _utc_to_et(utc_str: str) -> str:
    """'2026-06-12T22:41:00Z' → '06/12 06:41 PM EDT'."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        et = dt.astimezone(_EASTERN)
        abbr = "EDT" if et.dst() else "EST"
        return et.strftime(f"%m/%d %I:%M %p {abbr}").lstrip("0")
    except Exception:
        return utc_str[:16]


def load_existing() -> dict:
    fp = _DOCS / "data.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text())
        except json.JSONDecodeError:
            pass
    return {"sports": {}}


def render(sport_alias: str, block: dict, cfg: dict) -> None:
    _DOCS.mkdir(parents=True, exist_ok=True)

    data = load_existing()
    data.setdefault("sports", {})[sport_alias] = block
    data["last_updated_sport"] = sport_alias
    (_DOCS / "data.json").write_text(json.dumps(data, indent=1))

    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=True)
    env.filters["to_et"] = _utc_to_et

    tmpl = env.get_template("sgp.html.j2")
    html = tmpl.render(
        sports=data["sports"],
        default_sport=sport_alias,
        boost_defaults=cfg["boost"],
    )
    (_DOCS / "index.html").write_text(html)

    print(f"SGP dashboard: {block['n_sgps']} SGPs across "
          f"{len(block['games'])} games for {sport_alias}.")
    print(f"Output: {_DOCS / 'index.html'}")
