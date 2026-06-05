#!/usr/bin/env python
"""Snapshot the Sleeper-derived keeper history to a CSV for inspection.

    python scripts/build_history.py
Writes data/keeper_history_snapshot.csv — every current roster player with their
computed keep-year, original draft round, and eligibility. Handy for sanity
checks against the old spreadsheet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from kreeper import config, engine, history  # noqa: E402
from kreeper.adp import consensus  # noqa: E402
from kreeper.names import normalize_name  # noqa: E402


def main() -> int:
    season = config.current_season()
    H = history.build_history()
    cands = history.roster_candidates()
    lk = consensus.adp_lookup(season)
    rows = []
    for owner_id, pids in cands.items():
        mgr = config.manager_name(owner_id)
        for pid in pids:
            pm = H.player_meta(pid)
            if pm.position not in ("QB", "RB", "WR", "TE"):
                continue
            prof = H.keeper_profile(owner_id, pid, season)
            rank = lk.get(f"{normalize_name(pm.name)}|{pm.position.lower()}") or lk.get(normalize_name(pm.name))
            cost = engine.compute(prof, adp_rank=rank, is_rookie_keeper=False)
            rows.append({
                "manager": mgr, "player": pm.name, "pos": pm.position,
                "keep_year": cost.keep_year, "eligible": cost.eligible,
                "original_round": prof.get("original_round"),
                "adp_rank": int(rank) if rank else None,
                "reg_cost": cost.recommended_label, "acquired": prof.get("acquired_via"),
            })
    df = pd.DataFrame(rows).sort_values(["manager", "adp_rank"], na_position="last")
    out = config.DATA_DIR / "keeper_history_snapshot.csv"
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
