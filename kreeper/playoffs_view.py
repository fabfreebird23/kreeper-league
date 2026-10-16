"""The Playoffs page, drawn the way the Draft Room draws it.

One fact strip, "where you finish" as a bar per seed, your win % week by
week, the biggest game, then two drawers: where everyone lands, and your
players in the playoff weeks. Colours come from the hub's own theme tokens
(--panel, --line, --ink, --muted, --teal, --amber, --red), so the same file
reads right in Kreeper's black-and-royal, B&B's light purple and 7½ Men's
Bloody Sunday.
"""
from __future__ import annotations

import html
from typing import Callable, Optional

import streamlit as st

CSS = """<style>
.po-strip{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px;padding:6px 2px 12px;margin:0 0 12px;border-bottom:1px solid var(--line)}
.po-sf{display:inline-flex;align-items:baseline;gap:6px;font-size:13px;color:var(--muted);white-space:nowrap}
.po-sf b{font-family:var(--font-display);font-weight:600;font-size:19px;color:var(--ink)}
.po-sf b.g{color:var(--teal)} .po-sf b.a{color:var(--amber)} .po-sf b.d{color:var(--red)}
.po-sf i{font-style:normal;opacity:.75;font-size:12px}
.po-box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;max-width:820px}
.po-k{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.po-seeds{display:flex;gap:6px;align-items:flex-end;height:118px;margin-top:10px}
.po-sd{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:4px;min-width:0}
.po-sd i{display:block;width:100%;border-radius:5px 5px 2px 2px;background:var(--muted);opacity:.45}
.po-sd.in i{background:var(--teal);opacity:.9}
.po-sd.zero i{background:var(--line);opacity:1}
.po-sd.top b{color:var(--ink)}
.po-sd b{font-family:var(--mono);font-size:10px;font-weight:600;color:var(--muted)}
.po-sd span{font-family:var(--mono);font-size:10px;color:var(--muted)}
.po-cap{font-size:12.5px;color:var(--muted);margin-top:8px}
.po-cap b{color:var(--ink)}
.po-strip2{display:grid;gap:6px;max-width:820px;margin-top:8px}
.po-wk{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:7px 2px 6px;display:flex;flex-direction:column;align-items:center;gap:3px;height:118px;justify-content:flex-end;min-width:0}
.po-wk.big{border-color:var(--amber);box-shadow:inset 0 0 0 1px var(--amber)}
.po-wk span{font-family:var(--mono);font-size:9.5px;color:var(--muted);order:-2;margin-bottom:auto}
.po-wk b{font-family:var(--font-display);font-weight:600;font-size:16px;order:-1}
.po-wk i{display:block;width:58%;border-radius:3px;opacity:.6}
.po-wk em{font-style:normal;font-size:9.5px;color:var(--muted);max-width:92%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.po-g{color:var(--teal)} .po-a{color:var(--amber)} .po-d{color:var(--red)}
.po-wk i.po-g{background:var(--teal)} .po-wk i.po-a{background:var(--amber)} .po-wk i.po-d{background:var(--red)}
.po-big{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--amber);border-radius:12px;padding:10px 13px;margin-top:10px;max-width:820px}
.po-big .po-k{color:var(--amber)} .po-big .po-k b{color:var(--ink);font-weight:600;margin-left:6px}
.po-big div{font-size:13px;color:var(--muted);margin-top:5px;line-height:1.5}
.po-big div b{color:var(--ink)}
.po-t{width:100%;border-collapse:collapse;font-size:13px}
.po-t th{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);text-align:right;font-weight:600;padding:6px 8px;border-bottom:1px solid var(--line)}
.po-t th:first-child,.po-t td:first-child{text-align:left}
.po-t td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;color:var(--ink)}
.po-t tr.me td{font-weight:700}
.po-t tr.cut td{border-bottom:2px solid var(--amber)}
.po-t .chip{font-size:10.5px;padding:2px 7px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.po-t .chip.easy{color:var(--teal);border-color:var(--teal)} .po-t .chip.hard{color:var(--red);border-color:var(--red)}
.po-note{font-size:12px;color:var(--muted);margin:6px 0 2px;line-height:1.5;max-width:90ch}
@media (max-width:760px){.po-sf + .po-sf::before{display:none}.po-wk{height:104px}.po-wk em{font-size:8.5px}}
</style>"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def _tone(p: float) -> str:
    return "po-g" if p >= 60 else ("po-a" if p >= 50 else "po-d")


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def render(out: dict, me: Optional[str], name_of: Callable[[str], str], slate: Optional[dict] = None,
           pick_team_hint: str = "") -> None:
    """Draw the page from playoffs.outlook() (+ playoff_slate() for `me`)."""
    st.markdown(CSS, unsafe_allow_html=True)
    s, sim, teams = out["settings"], out.get("sim") or {}, out["teams"]
    pt = min(s["playoff_teams"], len(teams))
    pw = s["playoff_weeks"]
    pw_txt = f"{pw[0]}–{pw[-1]}" if len(pw) > 1 else (str(pw[0]) if pw else "—")
    odds = sim.get("teams") or {}
    mine = odds.get(me or "", {})

    # ---- the strip -----------------------------------------------------------
    facts = []
    if me and mine:
        p = mine["playoff_pct"]
        facts.append((f'{p}%', "g" if p >= 50 else ("a" if p >= 20 else "d"), "Playoff odds", f"top {pt} make it"))
        facts.append((f'{mine["avg_seed"]:.1f}', "", "Projected seed", f"of {len(teams)} teams"))
    else:
        facts.append((f"{pt}", "", "make the playoffs", f"of {len(teams)} teams"))
    facts.append((pw_txt, "", "Playoff weeks", "from this league's settings"))
    facts.append((str(out["weeks_left"]), "", "Weeks to play", "before the bracket"))
    st.markdown('<div class="po-strip">' + "".join(
        f'<span class="po-sf"><b class="{c}">{_e(v)}</b>{_e(l)}<i>{_e(sub)}</i></span>' for v, c, l, sub in facts)
        + '</div>', unsafe_allow_html=True)

    if not sim:
        st.markdown('<div class="po-note">The regular season is over — the bracket is set.</div>'
                    if out["weeks_left"] == 0 else
                    '<div class="po-note">No remaining schedule from Sleeper yet.</div>', unsafe_allow_html=True)
    elif me and sim.get("seeds"):
        _arc(out, me, name_of, pt)
    elif pick_team_hint:
        st.markdown(f'<div class="po-note">{pick_team_hint}</div>', unsafe_allow_html=True)

    # ---- the drawers --------------------------------------------------------
    if odds:
        lead = max(odds.items(), key=lambda kv: kv[1]["playoff_pct"])[0]
        with st.expander(f"**Where everyone lands**  ·  {len(teams)} teams · "
                         f"{name_of(lead)} most likely in", expanded=not me):
            rows = sorted(odds.items(), key=lambda kv: (-kv[1]["playoff_pct"], kv[1]["avg_seed"]))
            body = []
            for i, (o, r) in enumerate(rows):
                t = teams[o]
                cls = " ".join(x for x in ("me" if o == me else "", "cut" if i == pt - 1 else "") if x)
                rec = f'{t["wins"]}–{t["losses"]}' + (f'–{t["ties"]}' if t.get("ties") else "")
                body.append(f'<tr class="{cls}"><td>{_e(name_of(o))}</td><td>{rec}</td>'
                            f'<td>{t["mean"]:.0f}</td>'
                            f'<td class="{_tone(r["playoff_pct"] * 0.6 + 20)}">{r["playoff_pct"]}%</td>'
                            f'<td>{r["avg_seed"]:.1f}</td></tr>')
            st.markdown('<table class="po-t"><thead><tr><th>Team</th><th>Record</th><th>~Pts/wk</th>'
                        '<th>Playoffs</th><th>~Seed</th></tr></thead><tbody>' + "".join(body)
                        + '</tbody></table>', unsafe_allow_html=True)
            st.markdown(f'<div class="po-note">The line under the {_ordinal(pt)} team is the cut. '
                        '~Pts/wk is the strength each team is simulated at: its best lineup by this '
                        "week's projections, blended 60/40 with its actual scoring once two weeks are in.</div>",
                        unsafe_allow_html=True)
    if me and slate is not None:
        with st.expander(f"**Your players in the playoff weeks**  ·  weeks {pw_txt} strength of schedule"):
            rows = slate.get("rows") or []
            if not rows:
                st.markdown('<div class="po-note">No playoff-week schedule yet.</div>', unsafe_allow_html=True)
            else:
                head = "".join(f"<th>Wk {w}</th>" for w in pw)
                body = []
                for r in rows:
                    cells = "".join(f'<td>{_e(opp)}' + (f' <span style="opacity:.6">#{rk}</span>' if rk else "")
                                    + '</td>' for _w, opp, rk in r["weeks"])
                    g = r["grade"]
                    chip = (f'<span class="chip {g}">{ {"easy": "easy slate", "hard": "hard slate", "avg": "average"}[g] }</span>'
                            if g else "—")
                    body.append(f'<tr><td>{_e(r["name"])} <span style="opacity:.6">{_e(r["pos"])}</span></td>'
                                f'{cells}<td>{chip}</td></tr>')
                st.markdown(f'<table class="po-t"><thead><tr><th>Starter</th>{head}<th>Grade</th></tr></thead>'
                            '<tbody>' + "".join(body) + '</tbody></table>', unsafe_allow_html=True)
                st.markdown(f'<div class="po-note">#N is the opponent\'s rank against that position by '
                            f'fantasy points allowed per game ({_e(slate.get("label"))}); 1 is the stingiest '
                            f'of {slate.get("n_def", 32)}.</div>', unsafe_allow_html=True)


def _arc(out: dict, me: str, name_of: Callable[[str], str], pt: int) -> None:
    sim, t = out["sim"], out["teams"][me]
    seeds = sim["seeds"]
    top = max(seeds) or 1
    likely = seeds.index(max(seeds)) + 1
    bars = []
    for i, p in enumerate(seeds):
        cls = " ".join(x for x in ("in" if i < pt else "", "zero" if p == 0 else "",
                                   "top" if i + 1 == likely else "") if x)
        h = 3 if p == 0 else max(6, 78 * p / top)
        bars.append(f'<div class="po-sd {cls}"><b>{p}%</b><i style="height:{h:.0f}px"></i><span>{i + 1}</span></div>')
    rec = f'{t["wins"]}-{t["losses"]}' + (f'-{t["ties"]}' if t.get("ties") else "")
    st.markdown(f'<div class="po-box"><div class="po-k">Where you finish · {rec} now · 10,000 seasons</div>'
                f'<div class="po-seeds">{"".join(bars)}</div>'
                f'<div class="po-cap">Top {pt} make it. Most likely: <b>{_ordinal(likely)}</b>.</div></div>',
                unsafe_allow_html=True)
    weeks = sim.get("weeks") or []
    if not weeks:
        return
    # The biggest game is the one whose RESULT is in doubt AND moves the odds:
    # a 98% favourite you'd be crushed to lose is not where the season turns.
    lev = lambda w: w["swing"] * 4 * (w["p_win"] / 100) * (1 - w["p_win"] / 100)  # noqa: E731
    big = max(weeks, key=lev)
    cells = []
    for w in weeks:
        tn = _tone(w["p_win"])
        cells.append(f'<div class="po-wk{" big" if (w is big and lev(big) >= 3) else ""}">'
                     f'<span>W{w["week"]}</span><b class="{tn}">{w["p_win"]}</b>'
                     f'<i class="{tn}" style="height:{max(4, w["p_win"] * 0.42):.0f}px"></i>'
                     f'<em>{_e(name_of(w["opp"]))}</em></div>')
    st.markdown(f'<div class="po-k" style="margin-top:16px">Week by week · your win %</div>'
                f'<div class="po-strip2" style="grid-template-columns:repeat({len(weeks)},minmax(0,1fr))">'
                + "".join(cells) + '</div>', unsafe_allow_html=True)
    if lev(big) >= 3:
        st.markdown(f'<div class="po-big"><div class="po-k">Biggest game<b>Week {big["week"]} · vs '
                    f'{_e(name_of(big["opp"]))} · {big["p_win"]}%</b></div>'
                    f'<div>Win it and your odds go to <b class="po-g">{big["if_win"]}%</b>; lose and they '
                    f'drop to <b class="po-d">{big["if_lose"]}%</b>. No other game is both this close '
                    f'and this decisive.</div></div>', unsafe_allow_html=True)
