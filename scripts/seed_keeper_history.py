#!/usr/bin/env python
"""Seed the FULL keeper ledger (regular K1/K2/K3 designations) from the league's
historical spreadsheet, 2023-2025. Rookie keepers were seeded separately; this
merges the regular keepers in so keeper-YEAR counting is accurate even where
Sleeper's is_keeper flag is missing (e.g. Puka kept in 2024 but unflagged).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kreeper import sleeper, storage, config  # noqa: E402
from kreeper.names import normalize_name  # noqa: E402

NAME_TO_ID = {m["name"]: oid for oid, m in config.managers().items()}
players = sleeper.get_players()

_idx = {}
for pid, p in players.items():
    nm = normalize_name(p.get("full_name") or "")
    if not nm:
        continue
    skill = p.get("position") in ("QB", "RB", "WR", "TE")
    score = (1 if skill else 0, 1 if p.get("active") else 0, 1 if p.get("team") else 0)
    if nm not in _idx or score > _idx[nm][1]:
        _idx[nm] = (pid, score)
_idx = {k: v[0] for k, v in _idx.items()}


def resolve(name):
    return _idx.get(normalize_name(name))


# Regular keepers (K1/K2/K3) per the spreadsheet.
REG = {
    2023: {
        "Tanner Prible": ["Miles Sanders", "Deebo Samuel", "Amari Cooper"],
        "Chase Harris": ["Justin Jefferson", "Cooper Kupp", "Saquon Barkley"],
        "Jared Jacobs": ["CeeDee Lamb", "Dalvin Cook", "Najee Harris"],
        "Branigan Norton": ["Tyreek Hill", "Davante Adams", "Joe Mixon"],
        "Heath Gentis": ["Travis Kelce", "Nick Chubb", "Rhamondre Stevenson"],
        "Ned": ["Amon-Ra St. Brown", "A.J. Brown", "Jalen Hurts"],
        "Mike Clifton": ["Christian McCaffrey", "Garrett Wilson", "Alexander Mattison"],
        "Brandon Cliffton": ["Chris Olave", "Josh Jacobs", "Tony Pollard"],
    },
    2024: {
        "Tanner Prible": ["Christian McCaffrey", "A.J. Brown", "Drake London"],
        "Chase Harris": ["Amon-Ra St. Brown", "Chris Olave", "Nico Collins"],
        "Jared Jacobs": ["CeeDee Lamb", "Jonathan Taylor", "Kyren Williams"],
        "Branigan Norton": ["Isiah Pacheco", "Davante Adams", "Joe Mixon"],
        "Heath Gentis": ["DJ Moore", "Derrick Henry", "C.J. Stroud"],
        "Ned": ["Brandon Aiyuk", "Garrett Wilson", "Kenneth Walker"],
        "Mike Clifton": ["Trey McBride", "Tyreek Hill", "James Cook"],
        "Brandon Cliffton": ["Puka Nacua", "Sam LaPorta", "Justin Jefferson"],
    },
    2025: {
        "Tanner Prible": ["Saquon Barkley", "James Cook"],
        "Chase Harris": ["Terry McLaurin", "Nico Collins", "George Kittle"],
        "Jared Jacobs": ["Jonathan Taylor", "Kyren Williams", "Jameson Williams"],
        "Branigan Norton": ["Jauan Jennings", "Xavier Worthy"],
        "Heath Gentis": ["Tee Higgins", "Amon-Ra St. Brown", "Zay Flowers"],
        "Ned": ["Drake London", "Jaxon Smith-Njigba", "Chuba Hubbard"],
        "Mike Clifton": ["Breece Hall", "Jerry Jeudy", "Trey McBride"],
        "Brandon Cliffton": ["Puka Nacua", "Chase Brown", "Bucky Irving"],
    },
}

report = []
for yr, owners in REG.items():
    existing = storage.load(yr)  # has rookie keepers already
    for owner_name, names in owners.items():
        oid = NAME_TO_ID[owner_name]
        have = {str(s.get("player_id")) for s in existing.get(oid, [])}
        sel = list(existing.get(oid, []))
        for nm in names:
            pid = resolve(nm)
            if not pid:
                report.append(f"UNRESOLVED {yr} {owner_name}: {nm}")
                continue
            if str(pid) in have:
                continue  # already present (e.g. also a rookie keeper)
            sel.append({"player_id": pid, "player_name": nm, "is_rookie_keeper": False,
                        "keep_year": None, "cost_round": None})
        storage.save_manager_selections(oid, sel, yr)
    report.append(f"seeded {yr}: {len(owners)} teams")

Path("data/_seed_report.txt").write_text("\n".join(report))
print("\n".join(report))
