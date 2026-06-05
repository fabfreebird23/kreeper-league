#!/usr/bin/env python
"""Pull every enabled ADP source and rebuild the consensus CSV.

Run daily (cron / GitHub Actions) or on demand:
    python scripts/refresh_adp.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import config  # noqa: E402
from kreeper.adp import consensus  # noqa: E402


def main() -> int:
    season = config.current_season()
    scoring = config.league().get("scoring", "ppr")
    print(f"Refreshing ADP for {season} ({scoring})…")
    df = consensus.build(season, scoring)
    meta = consensus.load_meta(season)
    for k, v in meta.get("status", {}).items():
        print(f"  {'OK ' if v.startswith('ok') else 'ERR'} {k}: {v}")
    print(f"Wrote {len(df)} players · sources: {', '.join(meta.get('sources', []))}")
    # Fail the job only if every source died.
    ok = any(v.startswith("ok") for v in meta.get("status", {}).values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
