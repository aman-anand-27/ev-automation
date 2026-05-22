"""Write docs/data.json and docs/index.html from the computed rows."""

import json
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_DOCS = Path(__file__).parents[2] / "docs"
_TEMPLATES = Path(__file__).parent / "templates"


def render(rows: list[dict], cfg: dict) -> None:
    _DOCS.mkdir(exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    threshold = cfg["thresholds"]["hold_max_pct"]

    display_rows = [r for r in rows if r["hold_pct"] <= threshold]

    pre_game = [r for r in display_rows if not r.get("is_live")]
    live_rows = [r for r in display_rows if r.get("is_live")]

    qualified = [r for r in pre_game if r["qualified"]]
    unqualified = [r for r in pre_game if not r["qualified"]]

    data = {
        "generated_at": now,
        "thresholds": cfg["thresholds"],
        "rows": display_rows,
    }
    (_DOCS / "data.json").write_text(json.dumps(data, indent=2))

    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=True)
    tmpl = env.get_template("index.html.j2")
    html = tmpl.render(
        generated_at=now,
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
