#!/usr/bin/env python3
"""Testscript: log in bij Coolblue en laat zien welke prijsdata de API teruggeeft.

Draai dit op je eigen computer (je wachtwoord wordt gevraagd en nergens
opgeslagen of geprint):

    cd "Coolblue Energy HA"
    python3 -m venv .venv && .venv/bin/pip install aiohttp beautifulsoup4
    .venv/bin/python probe.py

Het schrijft probe_output.json weg (zonder wachtwoord). Debiteurnummer en
locatie-ID worden daarin gemaskeerd, zodat je het bestand veilig kunt delen.
"""

from __future__ import annotations

import asyncio
import getpass
import importlib.util
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE / "custom_components" / "coolblue_prices"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"coolblue_prices.{name}", PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the integration modules without needing Home Assistant installed.
sys.modules["coolblue_prices"] = type(sys)("coolblue_prices")
sys.modules["coolblue_prices"].__path__ = [str(PKG)]
pricing = _load("pricing")
_load("auth")
api_mod = _load("api")


def _mask(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, s[:2] + "***")
    return text


def _short(rows, n=3):
    return {"count": len(rows) if isinstance(rows, list) else None,
            "first_rows": rows[:n] if isinstance(rows, list) else rows}


async def main() -> None:
    email = input("Coolblue e-mailadres: ").strip()
    password = getpass.getpass("Wachtwoord (wordt niet getoond): ")
    out: dict = {}

    async with api_mod.CoolblueApi(email, password) as api:
        print("Inloggen…")
        debtor, location = await api.get_energy_ids()
        print("Ingelogd. Contract gevonden.")

        today = date.today()
        days = {"yesterday": today - timedelta(days=1), "today": today,
                "tomorrow": today + timedelta(days=1)}

        for label, day in days.items():
            for commodity in ("electricity", "gas", "costs"):
                key = f"{label}_{commodity}"
                try:
                    rows = await api.get_insights(debtor, location, day, commodity)
                    out[key] = _short(rows)
                    if commodity == "electricity":
                        slots = api_mod.parse_price_rows(rows, day)
                        out[key]["parsed_prices"] = [s.as_dict() for s in slots]
                        print(f"{label:9} stroom: {len(rows)} rijen, {len(slots)} prijzen"
                              + (f" (bijv. {slots[0].start:%H:%M} = €{slots[0].price:.4f})" if slots else ""))
                except Exception as err:  # noqa: BLE001
                    out[key] = {"error": repr(err)}
                    print(f"{label:9} {commodity}: fout {err!r}")

        # Quarter-hour granularity, just to see if the portal supports it.
        for gran in ("QUARTER_HOUR", "QUARTER"):
            try:
                rows = await api.get_insights(debtor, location, today, "electricity", gran)
                out[f"today_electricity_{gran}"] = _short(rows, 2)
                print(f"granularity={gran}: {len(rows)} rijen")
            except Exception as err:  # noqa: BLE001
                out[f"today_electricity_{gran}"] = {"error": repr(err)}

        # Look for other price-related API calls in the portal pages.
        session = await api._auth.get_session()
        found: set[str] = set()
        for url in (
            api_mod.ENERGY_URL,
            "https://www.coolblue.nl/nl/mijn-coolblue-account/energie",
            "https://www.coolblue.nl/nl/mijn-coolblue-account/energie/tarieven",
            "https://www.coolblue.nl/nl/mijn-coolblue-account/energie/dynamische-prijzen",
        ):
            try:
                async with session.get(url) as r:
                    html = await r.text()
                    out.setdefault("pages", {})[url] = r.status
            except Exception as err:  # noqa: BLE001
                out.setdefault("pages", {})[url] = repr(err)
                continue
            for m in re.findall(r'/api/[A-Za-z0-9_\-/]+', html):
                found.add(m)
            for m in re.findall(r'"([a-zA-Z]*[Pp]rice[a-zA-Z]*)"', html):
                found.add(f"key:{m}")
        out["api_paths_and_price_keys"] = sorted(found)

    text = _mask(json.dumps(out, indent=2, default=str), debtor, location)
    (HERE / "probe_output.json").write_text(text)
    print("\nKlaar: probe_output.json geschreven.")


if __name__ == "__main__":
    asyncio.run(main())
