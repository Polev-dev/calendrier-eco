# Temps forts éco 📅

Calendrier `.ics` des publications économiques majeures (zone euro 🇪🇺 + États-Unis 🇺🇸), mis à jour automatiquement chaque jour par GitHub Actions à partir du flux gratuit de Forex Factory.

**Abonnement :** `webcal://polev-dev.github.io/calendrier-eco/calendrier.ics`

- Filtre : liste d'indicateurs clés (`KEY_EVENTS`) + tout ce que Forex Factory classe en impact fort, moins les publications trop fréquentes (`EXCLUDE`). Voir `scripts/build_calendar.py`.
- Les annonces d'un même pays à la même heure sont regroupées en un seul événement.
- Backtest : `python scripts/backtest.py` → `backtest/RESULTATS.md`.
