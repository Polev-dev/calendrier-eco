#!/usr/bin/env python3
"""Backtest du filtre : compare, semaine par semaine, les temps forts d'une source
indépendante (ThriveInMarkets, impact "high", US + zone euro) avec ce que garde
build_calendar.keep() sur les données Forex Factory.

- Semaines avec archive FF réelle (depuis le 5 oct.) : test sur les vrais événements FF.
- Semaines plus anciennes : test simulé sur le titre FF standard de l'indicateur
  (le filtre étant basé sur les titres, le résultat ne dépend pas de l'impact FF).
"""
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_calendar import keep, translate  # noqa: E402

REF = json.loads((ROOT / "backtest" / "thrive_weeks.json").read_text())
FF = json.loads((ROOT / "backtest" / "ff_archive.json").read_text())
FF_START = date(2026, 10, 5)  # début de l'archive FF complète

# catégorie : (regex sur le nom de la référence, pays FF, regex sur le titre FF, titre FF type)
CATS = [
    ("Décision Fed", r"fomc rate decision", "USD", r"^federal funds rate", "Federal Funds Rate"),
    ("Minutes Fed", r"fomc.*minutes", "USD", r"^fomc meeting minutes", "FOMC Meeting Minutes"),
    ("Discours président Fed", r"fed chair|jackson hole", "USD", r"fed chair|jackson hole", "Fed Chairman Warsh Speaks"),
    ("Discours Williams (Fed NY)", r"williams", "USD", r"williams", "FOMC Member Williams Speaks"),
    ("CPI US", r"^(us )?cpi\b", "USD", r"^(core )?cpi m/m", "CPI m/m"),
    ("PPI US", r"^ppi\b", "USD", r"^(core )?ppi m/m", "PPI m/m"),
    ("Emploi NFP", r"nonfarm payrolls", "USD", r"^non-farm employment change", "Non-Farm Employment Change"),
    ("Emploi ADP", r"^adp", "USD", r"^adp non-farm", "ADP Non-Farm Employment Change"),
    ("JOLTS", r"jolts", "USD", r"^jolts", "JOLTS Job Openings"),
    ("ISM manufacturier", r"ism manufacturing", "USD", r"^ism manufacturing", "ISM Manufacturing PMI"),
    ("ISM services", r"ism services", "USD", r"^ism services", "ISM Services PMI"),
    ("PCE", r"pce", "USD", r"pce price index m/m", "Core PCE Price Index m/m"),
    ("PIB US", r"gdp", "USD", r"gdp q/q$", "Advance GDP q/q"),
    ("Ventes au détail US", r"retail sales", "USD", r"^(core )?retail sales m/m", "Retail Sales m/m"),
    ("Confiance conso (CB)", r"conference board", "USD", r"^cb consumer confidence", "CB Consumer Confidence"),
    ("Biens durables", r"durable goods", "USD", r"durable goods", "Durable Goods Orders m/m"),
    ("Coût de l'emploi", r"employment cost", "USD", r"employment cost", "Employment Cost Index q/q"),
    ("Ventes logements anciens", r"existing home", "USD", r"existing home", "Existing Home Sales"),
    ("Inscriptions chômage", r"jobless claims", "USD", r"unemployment claims", "Unemployment Claims"),
    ("PMI flash US", r"flash pmi", "USD", r"^flash (manufacturing|services) pmi", "Flash Manufacturing PMI"),
    ("Jour férié US", r"thanksgiving|markets closed", "USD", r"holiday", "Bank Holiday"),
    ("Élections US", r"election", "USD", r"election", "Congressional Elections"),
    ("Décision BCE", r"ecb rate decision", "EUR", r"^main refinancing rate", "Main Refinancing Rate"),
    ("Inflation flash zone euro", r"eurozone.*(cpi|hicp)", "EUR", r"^(core )?cpi flash estimate", "CPI Flash Estimate y/y"),
    ("PMI flash zone euro / Allemagne", r"flash pmi", "EUR", r"flash (manufacturing|services) pmi", "Flash Manufacturing PMI"),
    ("Inflation Allemagne", r"germany cpi", "EUR", r"^german prelim cpi", "German Prelim CPI m/m"),
    ("PIB Allemagne", r"germany gdp", "EUR", r"^german prelim gdp", "German Prelim GDP q/q"),
    ("PIB zone euro", r"eurozone.*gdp", "EUR", r"flash gdp q/q", "Prelim Flash GDP q/q"),
    ("Ifo", r"ifo", "EUR", r"ifo", "German ifo Business Climate"),
    ("Inflation Espagne", r"spain", "EUR", r"^spanish", "Spanish Flash CPI y/y"),
]
NOT_ON_FF = r"credit rating|summit|benchmark"


def ref_events():
    for week, w in sorted(REF.items()):
        for e in w["events"]:
            if e["country"] not in ("US", "EU") or e.get("eventType") in ("earnings", "oil", "crypto"):
                continue
            if e["impact"] == "high" or (e.get("eventType") == "holiday" and "closed" in e["event"].lower()
                                         and "bond" not in e["event"].lower()):
                yield week, e


def main():
    ff_by_day = defaultdict(list)
    for ev in FF:
        ff_by_day[ev["date"][:10]].append(ev)
    rows, stats = [], defaultdict(int)
    for week, e in ref_events():
        name = e["event"]
        country = "USD" if e["country"] == "US" else "EUR"
        cats = [c for c in CATS if c[2] == country and re.search(c[1], name.lower())]
        d = date.fromisoformat(e["date"])
        if re.search(NOT_ON_FF, name.lower()):
            rows.append((week, e["date"], name, "hors calendrier FF", "—"))
            stats["hors FF"] += 1
            continue
        if not cats:
            rows.append((week, e["date"], name, "non classé", "?"))
            stats["non classé"] += 1
            continue
        for label, _, _, ff_re, canonical in cats:
            if d >= FF_START:
                cands = [x for k in (d - timedelta(days=1), d, d + timedelta(days=1))
                         for x in ff_by_day[k.isoformat()]
                         if x["country"] == country and re.search(ff_re, x["title"].lower())]
                if not cands:
                    verdict, mode = "absent de l'archive FF", "réel"
                else:
                    verdict = "OK" if any(keep(x) for x in cands) else "RATÉ (filtré)"
                    mode = "réel"
            else:
                verdict = "OK" if keep({"country": country, "title": canonical, "impact": "Medium",
                                        "date": e["date"]}) else "RATÉ (filtré)"
                mode = "simulé"
            stats[verdict] += 1
            rows.append((week, e["date"], f"{name} → {label}", verdict, mode))

    # volume par semaine (archive réelle)
    vol = defaultdict(int)
    for ev in FF:
        if keep(ev):
            vol[(datetime.fromisoformat(ev["date"]).date() - timedelta(days=datetime.fromisoformat(ev["date"]).weekday())).isoformat()] += 1

    out = ["# Backtest du calendrier", "", "| Semaine | Date | Temps fort (référence) | Résultat | Test |",
           "|---|---|---|---|---|"]
    out += [f"| {w} | {d} | {n} | {v} | {m} |" for w, d, n, v, m in rows]
    out += ["", "## Bilan", ""] + [f"- {k} : {v}" for k, v in sorted(stats.items())]
    out += ["", "## Événements gardés par semaine (archive FF réelle, avant regroupement)", ""]
    out += [f"- {w} : {n}" for w, n in sorted(vol.items())]
    (ROOT / "backtest" / "RESULTATS.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[-(len(stats) + len(vol) + 5):]))
    for w, d, n, v, m in rows:
        if v not in ("OK",):
            print(f"  ! {d} {n} -> {v} ({m})")


if __name__ == "__main__":
    main()
