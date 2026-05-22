"""Apply qualification thresholds to computed rows."""


def qualify_rows(rows: list[dict], cfg: dict) -> list[dict]:
    """Set qualified=True/False and populate disqualify_reasons on each row in-place."""
    t = cfg["thresholds"]
    hold_max = t["hold_max_pct"]
    tolerance = t["dk_consensus_tolerance_pp"]

    for row in rows:
        reasons: list[str] = []

        if row["hold_pct"] > hold_max:
            reasons.append(f"hold {row['hold_pct']:.1f}% > {hold_max}%")

        if row["consensus_implied_pct"] is None:
            reasons.append("insufficient consensus books")
        elif abs(row["dk_implied_pct"] - row["consensus_implied_pct"]) > tolerance:
            diff = row["dk_implied_pct"] - row["consensus_implied_pct"]
            reasons.append(f"DK {diff:+.1f}pp vs consensus")

        row["qualified"] = not reasons
        row["disqualify_reasons"] = reasons

    return rows
