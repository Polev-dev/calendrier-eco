#!/usr/bin/env python3
"""Construit un calendrier .ics des temps forts économiques (EUR + USD).

Source : flux JSON gratuit de Forex Factory (semaine en cours + semaine suivante).
Les événements déjà vus sont conservés dans data/events.json pour garder l'historique.
"""
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "events.json"
OUT = ROOT / "docs" / "calendrier.ics"

FEEDS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

# Devises suivies
COUNTRIES = {"USD": "🇺🇸", "EUR": "🇪🇺"}

# Indicateurs clés gardés quel que soit l'impact donné par Forex Factory
# (FF classe par ex. l'ISM, le JOLTS ou l'inflation flash zone euro en "Medium").
# Expressions régulières testées sur le titre, en minuscules.
KEY_EVENTS = {
    "USD": [
        r"^federal funds rate", r"^fomc (statement|press conference|meeting minutes)",
        r"^fed chair", r"^(core )?cpi m/m", r"^(core )?ppi m/m", r"^non-farm employment change",
        r"^unemployment rate", r"^average hourly earnings", r"^(core )?pce price index m/m",
        r"^(advance|prelim|final) gdp q/q", r"^(core )?retail sales m/m", r"^ism (manufacturing|services) pmi",
        r"^jolts job openings", r"^cb consumer confidence", r"^prelim uom consumer sentiment",
        r"^(core )?durable goods orders", r"^employment cost index", r"^adp non-farm",
        r"^flash (manufacturing|services) pmi", r"election", r"jackson hole",
    ],
    "EUR": [
        r"^main refinancing rate", r"^monetary policy statement", r"^ecb press conference",
        r"^(core )?cpi flash estimate", r"^flash (manufacturing|services) pmi", r"^german ifo",
        r"^german prelim cpi m/m", r"^french (flash|prelim) cpi m/m", r"^(prelim )?flash gdp q/q",
        r"^german prelim gdp q/q", r"^ecb monetary policy meeting accounts",
    ],
}
# Événements jamais gardés (trop fréquents / redondants), même en "High"
EXCLUDE = [r"^unemployment claims", r"^german flash", r"^french flash (manufacturing|services)",
           r"gdp price index", r"y/y$"]

# Traductions (correspondance sur le début du titre, insensible à la casse)
TRANSLATIONS = [
    ("federal funds rate", "Décision de taux de la Fed"),
    ("fomc statement", "Communiqué de la Fed"),
    ("fomc press conference", "Conférence de presse de la Fed"),
    ("fomc meeting minutes", "Minutes de la Fed"),
    ("fomc economic projections", "Projections économiques de la Fed"),
    ("fed chair", "Discours du président de la Fed"),
    ("congressional elections", "Élections de mi-mandat US"),
    ("adp non-farm employment change", "Emploi privé ADP"),
    ("employment cost index", "Coût de l'emploi (ECI)"),
    ("german prelim gdp", "PIB Allemagne (provisoire)"),
    ("flash gdp", "PIB zone euro (flash)"),
    ("monetary policy statement", "Communiqué de la BCE"),
    ("beige book", "Livre beige de la Fed"),
    ("main refinancing rate", "Décision de taux de la BCE"),
    ("monetary policy statement", "Communiqué de la BCE"),
    ("ecb press conference", "Conférence de presse de la BCE"),
    ("ecb president", "Discours de la présidente de la BCE"),
    ("ecb monetary policy meeting accounts", "Minutes de la BCE"),
    ("non-farm employment change", "Emploi américain (NFP)"),
    ("unemployment rate", "Taux de chômage"),
    ("average hourly earnings", "Salaire horaire moyen"),
    ("unemployment claims", "Inscriptions au chômage"),
    ("jolts job openings", "Offres d'emploi JOLTS"),
    ("adp non-farm", "Emploi privé ADP"),
    ("core cpi", "Inflation sous-jacente (CPI)"),
    ("cpi", "Inflation (CPI)"),
    ("core ppi", "Prix à la production sous-jacents"),
    ("ppi", "Prix à la production"),
    ("core pce price index", "Inflation PCE sous-jacente"),
    ("pce price index", "Inflation PCE"),
    ("advance gdp", "PIB (1re estimation)"),
    ("prelim gdp", "PIB (2e estimation)"),
    ("final gdp", "PIB (estimation finale)"),
    ("gdp", "PIB"),
    ("core retail sales", "Ventes au détail hors auto"),
    ("retail sales", "Ventes au détail"),
    ("ism manufacturing pmi", "ISM manufacturier"),
    ("ism services pmi", "ISM services"),
    ("cb consumer confidence", "Confiance des consommateurs (Conference Board)"),
    ("prelim uom consumer sentiment", "Moral des ménages Michigan"),
    ("revised uom consumer sentiment", "Moral des ménages Michigan (révisé)"),
    ("core durable goods orders", "Commandes de biens durables (hors transport)"),
    ("durable goods orders", "Commandes de biens durables"),
    ("german ifo business climate", "Climat des affaires Ifo (Allemagne)"),
    ("french flash cpi", "Inflation en France (provisoire)"),
    ("french prelim cpi", "Inflation en France (provisoire)"),
    ("german prelim cpi", "Inflation en Allemagne (provisoire)"),
    ("core cpi flash estimate", "Inflation sous-jacente zone euro (flash)"),
    ("cpi flash estimate", "Inflation zone euro (flash)"),
    ("french flash manufacturing pmi", "PMI manufacturier France (flash)"),
    ("french flash services pmi", "PMI services France (flash)"),
    ("german flash manufacturing pmi", "PMI manufacturier Allemagne (flash)"),
    ("german flash services pmi", "PMI services Allemagne (flash)"),
    ("flash manufacturing pmi", "PMI manufacturier (flash)"),
    ("flash services pmi", "PMI services (flash)"),
    ("bank holiday", "Jour férié US – Wall Street fermée"),
    ("thanksgiving", "Thanksgiving – Wall Street fermée"),
    ("christmas", "Noël – marchés fermés"),
    ("new year", "Jour de l'an – marchés fermés"),
]

IMPACT_FR = {"High": "Fort", "Medium": "Moyen", "Low": "Faible", "Holiday": "Férié"}


def translate(title: str, suffix: bool = True) -> str:
    low = title.lower()
    matches = [(k, fr) for k, fr in TRANSLATIONS if k in low]
    if not matches:
        return title
    _, fr = max(matches, key=lambda m: len(m[0]))  # la correspondance la plus précise
    suffixes = {" m/m": " (sur un mois)", " q/q": " (sur un trimestre)", " y/y": " (sur un an)"}
    if not suffix:
        return fr
    return fr + next((v for k, v in suffixes.items() if low.endswith(k)), "")


def keep(ev: dict) -> bool:
    country = ev.get("country")
    if country not in COUNTRIES:
        return False
    title = ev.get("title", "").lower()
    if any(re.search(p, title) for p in EXCLUDE):
        # le y/y est redondant avec le m/m publié à la même heure, sauf s'il n'existe qu'en y/y
        if not (title.endswith("y/y") and "flash estimate" in title):
            return False
    if ev.get("impact") == "Holiday":
        return country == "USD" and "daylight" not in title
    if any(re.search(p, title) for p in KEY_EVENTS[country]):
        return True
    return ev.get("impact") == "High"


def fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "calendrier-eco/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:  # le flux "semaine suivante" n'existe pas toujours
        print(f"[warn] {url}: {e}", file=sys.stderr)
        return []


def uid(ev: dict) -> str:
    raw = f"{ev['country']}|{ev['title']}|{ev['date'][:10]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16] + "@calendrier-eco"


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> str:
    out, b = [], line.encode()
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode())
        b = b[cut:]
    out.append(b.decode())
    return "\r\n ".join(out)



# ---------------------------------------------------------------------------
# Semaines à venir : dates prévues (remplacées par Forex Factory la semaine venue)
# ---------------------------------------------------------------------------
HORIZON_DAYS = 28
THRIVE = "https://thriveinmarkets.com/calendar"
THRIVE_INDICATORS = ["cpi", "nfp", "fomc", "core-pce", "gdp", "ppi", "retail-sales", "pmi"]
MANUAL = ROOT / "data" / "planning_manuel.json"

# (pays, regex sur le nom anglais, libellé français) — l'ordre compte
PLANNED_LABELS = [
    ("USD", r"fomc (rate decision|meeting)", "Décision de taux de la Fed"),
    ("USD", r"fomc.*minutes", "Minutes de la Fed"),
    ("USD", r"fed chair|jackson hole", "Discours du président de la Fed"),
    ("USD", r"\bppi\b", "Prix à la production"),
    ("USD", r"\bcpi\b", "Inflation (CPI)"),
    ("USD", r"nonfarm|payrolls", "Emploi américain (NFP) · Taux de chômage"),
    ("USD", r"^adp", "Emploi privé ADP"),
    ("USD", r"jolts", "Offres d'emploi JOLTS"),
    ("USD", r"ism manufacturing", "ISM manufacturier"),
    ("USD", r"ism services", "ISM services"),
    ("USD", r"flash pmi", "PMI manufacturier (flash) · PMI services (flash)"),
    ("USD", r"pce|personal income", "Inflation PCE"),
    ("USD", r"gdp.*(second|2nd|prelim)", "PIB (2e estimation)"),
    ("USD", r"gdp.*(third|final)", "PIB (estimation finale)"),
    ("USD", r"gdp", "PIB (1re estimation)"),
    ("USD", r"retail sales", "Ventes au détail"),
    ("USD", r"conference board|consumer confidence", "Confiance des consommateurs (Conference Board)"),
    ("USD", r"durable goods", "Commandes de biens durables"),
    ("USD", r"employment cost", "Coût de l'emploi (ECI)"),
    ("USD", r"thanksgiving|christmas|new year|markets? closed", "Jour férié US – Wall Street fermée"),
    ("EUR", r"ecb (rate )?decision", "Décision de taux de la BCE"),
    ("EUR", r"ecb.*(account|minutes)", "Minutes de la BCE"),
    ("EUR", r"eurozone.*(cpi|hicp).*flash|eurozone flash cpi|eurozone hicp flash", "Inflation zone euro (flash)"),
    ("EUR", r"(eurozone|germany).*flash pmi|flash pmis", "PMI manufacturier (flash) · PMI services (flash)"),
    ("EUR", r"ifo", "Climat des affaires Ifo (Allemagne)"),
    ("EUR", r"german[y]? (prelim |flash )?cpi(?! final)", "Inflation en Allemagne (provisoire)"),
    ("EUR", r"france.*(prelim|flash).*cpi|french.*cpi", "Inflation en France (provisoire)"),
    ("EUR", r"eurozone.*gdp.*flash|eurozone gdp", "PIB zone euro (flash)"),
]


def planned_label(country: str, name: str):
    low = name.lower()
    if "final" in low and ("cpi" in low or "hicp" in low or "pmi" in low):
        return None  # les versions définitives ne sont pas des temps forts
    for c, rx, label in PLANNED_LABELS:
        if c == country and re.search(rx, low):
            return label
    return None


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (calendrier-eco)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"[warn] {url}: {e}", file=sys.stderr)
        return ""


def planned_from_indicator_pages():
    out = []
    days = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
    for slug in THRIVE_INDICATORS:
        page = fetch_text(f"{THRIVE}/indicator/{slug}/")
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        t = re.sub(r"\s+", " ", t)
        seg = t[t.find("Upcoming"):t.find("Past releases")]
        for d, hm, name in re.findall(
                rf"(?:{days}) (\d{{1,2}} \w+ \d{{4}})(?: Next)? (\d\d:\d\d) UTC (.*?)"
                rf"(?= View on calendar| (?:{days}) \d| Date UTC| Year schedule|$)", seg):
            try:
                when = datetime.strptime(f"{d} {hm}", "%d %B %Y %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            label = planned_label("USD", name if slug != "fomc" else "FOMC rate decision")
            if label:
                out.append({"country": "USD", "label": label, "title": name, "date": when.isoformat(),
                            "source": "calendrier officiel (via ThriveInMarkets)"})
    return out


def planned_from_week_pages(today):
    out = []
    monday = today - timedelta(days=today.weekday())
    for k in range(1, HORIZON_DAYS // 7 + 1):
        week = monday + timedelta(weeks=k)
        page = fetch_text(f"{THRIVE}/{week.isoformat()}/")
        chunks = re.findall(r'self\.__next_f\.push\(\[1,(".*?")\]\)</script>', page, re.S)
        try:
            full = "".join(json.loads(c) for c in chunks)
            i = full.find('{"week":{"weekOf"')
            if i < 0:
                continue
            obj, _ = json.JSONDecoder().raw_decode(full[i:])
        except Exception as e:
            print(f"[warn] semaine {week}: {e}", file=sys.stderr)
            continue
        for e in obj["week"].get("events", []):
            country = {"US": "USD", "EU": "EUR"}.get(e.get("country"))
            if not country or e.get("eventType") in ("earnings", "oil", "crypto"):
                continue
            label = planned_label(country, e["event"])
            if not label:
                continue
            m = re.match(r"(\d\d):(\d\d)", e.get("time") or "")
            when = datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
            if m and "holiday" not in (e.get("eventType") or "") and "Jour férié" not in label:
                when = when.replace(hour=int(m[1]), minute=int(m[2]))
            out.append({"country": country, "label": label, "title": e["event"], "date": when.isoformat(),
                        "source": "aperçu de la semaine (ThriveInMarkets)",
                        "impact": "Holiday" if "Jour férié" in label else ""})
    return out


def planned_events(ff_events):
    today = datetime.now(timezone.utc).date()
    events = []
    if MANUAL.exists():
        manual = json.loads(MANUAL.read_text())
        if not any(datetime.fromisoformat(e["date"]).date() > today + timedelta(days=45) for e in manual):
            print("::warning::data/planning_manuel.json : ajouter les prochaines dates BCE / Eurostat")
        for e in manual:
            events.append(dict(e, title=e["label"], source=e.get("source", "calendrier officiel")))
    events += planned_from_indicator_pages() + planned_from_week_pages(today)
    # la semaine couverte par Forex Factory fait foi : on retire les dates prévues de cette semaine
    ff_days = [datetime.fromisoformat(e["date"]).date() for e in ff_events]
    if ff_days:
        start = min(ff_days) - timedelta(days=min(ff_days).weekday())
        ff_end = max(ff_days) + timedelta(days=6 - max(ff_days).weekday())
    else:
        start = ff_end = today - timedelta(days=1)
    seen, out = set(), []
    for e in sorted(events, key=lambda e: e["date"]):
        day = datetime.fromisoformat(e["date"]).date()
        if day <= ff_end or day > today + timedelta(days=HORIZON_DAYS):
            continue
        key = (e["country"], day, e["label"])
        if key in seen:
            continue
        seen.add(key)
        e["planned"] = True
        out.append(e)
    return out


def build_ics(events: list) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//calendrier-eco//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Temps forts éco",
        "X-WR-CALDESC:Publications économiques majeures (zone euro + États-Unis)",
        "X-WR-TIMEZONE:Europe/Paris",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    # regroupe les annonces d'un même pays à la même heure en un seul événement
    groups = {}
    for ev in sorted(events, key=lambda e: (e["date"], e["title"])):
        groups.setdefault((ev["country"], ev["date"]), []).append(ev)
    for (country, date), evs in sorted(groups.items(), key=lambda g: g[0][1]):
        start = datetime.fromisoformat(date)
        flag = COUNTRIES[country]
        def lab(e, suffix=True):
            return e.get("label") or translate(e["title"], suffix)

        if len(evs) == 1:
            name = lab(evs[0])
        else:  # titres courts, sans doublons (ex. biens durables / biens durables hors transport)
            names = list(dict.fromkeys(lab(e, False) for e in evs))
            names = [n for n in names if not any(o != n and n.startswith(o) for o in names)]
            name = " · ".join(names)
        all_day = any(e.get("impact") == "Holiday" for e in evs) or (start.hour == 0 and start.minute == 0)
        desc = []
        for e in evs:
            if e.get("planned"):
                desc.append(f"{e['label']} — date prévue, source : {e['source']}. "
                            "Confirmée et complétée (prévision, précédent) la semaine de la publication.")
                continue
            line = f"{translate(e['title'])} — impact {IMPACT_FR.get(e.get('impact'), e.get('impact')).lower()}"
            if e.get("forecast"):
                line += f", prévision {e['forecast']}"
            if e.get("previous"):
                line += f", précédent {e['previous']}"
            desc.append(line)
        ev = {"country": country, "title": "+".join(e["title"] for e in evs), "date": date}
        lines += ["BEGIN:VEVENT", f"UID:{uid(ev)}", f"DTSTAMP:{now}"]
        if all_day:
            d = start.date()
            lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                      "TRANSP:TRANSPARENT"]
        else:
            s = start.astimezone(timezone.utc)
            lines += [f"DTSTART:{s:%Y%m%dT%H%M%SZ}", f"DTEND:{s + timedelta(minutes=15):%Y%m%dT%H%M%SZ}",
                      "TRANSP:TRANSPARENT"]
        lines += [fold(f"SUMMARY:{esc(flag + ' ' + name)}"), fold("DESCRIPTION:" + esc("\n".join(desc))),
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    store = json.loads(STORE.read_text()) if STORE.exists() else {}
    fetched = [ev for url in FEEDS for ev in fetch(url)]
    if not fetched and not store:
        sys.exit("Aucune donnée récupérée.")
    for ev in fetched:
        if keep(ev):
            store[uid(ev)] = ev  # met à jour prévisions / horaires
    # garde 6 mois d'historique
    cutoff = datetime.now(timezone.utc) - timedelta(days=183)
    store = {k: v for k, v in store.items() if datetime.fromisoformat(v["date"]) >= cutoff}
    STORE.parent.mkdir(exist_ok=True)
    OUT.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True))
    planned = planned_events(fetched or list(store.values()))
    OUT.write_text(build_ics(list(store.values()) + planned), newline="")
    print(f"{len(store)} événements Forex Factory + {len(planned)} dates prévues.")


if __name__ == "__main__":
    main()
