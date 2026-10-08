# Coolblue Energie Prijzen voor Home Assistant

Custom integration die de dynamische stroomprijzen uit je **eigen Coolblue-account**
haalt (dezelfde bron als de Coolblue-app) en ze als sensoren in Home Assistant zet.

> Coolblue heeft geen officiële API. Deze integratie logt in zoals de website dat doet
> en leest de ongedocumenteerde endpoint `/api/insights`. Als Coolblue het portaal
> aanpast, kan de integratie breken. De login is overgenomen uit
> [barisdemirdelen/homeassistant-coolblue-energy](https://github.com/barisdemirdelen/homeassistant-coolblue-energy)
> (MIT).

## Eerst testen: `probe.py`

Voordat je de integratie in HA zet, kijk je beter eerst wat Coolblue voor jouw contract teruggeeft:

```bash
cd "~/Claude/Projects/Coolblue Energy HA"
python3 -m venv .venv
.venv/bin/pip install aiohttp beautifulsoup4
.venv/bin/python probe.py
```

Het script vraagt om je e-mailadres en wachtwoord. Je wachtwoord wordt niet opgeslagen.
Daarna schrijft het `probe_output.json` weg, met je contractnummers gemaskeerd.
Daarin staat:
- of er prijzen voor **vandaag** en **morgen** komen
- of het portaal **kwartierprijzen** levert
- welke gas- en kostenvelden er zijn
- welke andere prijs-endpoints in het portaal voorkomen

## Installeren via HACS

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MaikelvdB07&repository=ha-coolblue-energie&category=integration)

1. Klik op de knop hierboven. Of ga in Home Assistant naar **HACS → ⋮ → Custom repositories**, voeg
   `https://github.com/MaikelvdB07/ha-coolblue-energie` toe en kies categorie **Integration**.
2. Zoek **Coolblue Energie Prijzen**, klik op **Download** en herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen → Coolblue Energie Prijzen**.
4. Log in met je Coolblue-account.
5. Open **Configureren** en controleer de prijsinstellingen (zie hieronder).

Handmatig kan ook: kopieer `custom_components/coolblue_prices` naar `/config/custom_components/` en herstart.

## Entiteiten

| Entiteit | Betekenis |
|---|---|
| `sensor.coolblue_energie_stroomprijs` | Huidige all-in stroomprijs. De attributen `prices_today` en `prices_tomorrow` zijn bruikbaar voor ApexCharts. |
| `sensor.coolblue_energie_stroomprijs_volgend_uur` | Prijs van het volgende blok |
| `sensor.coolblue_energie_terugleverprijs` | Marktprijs min de inkoopvergoeding (met dezelfde attributen) |
| `sensor.coolblue_energie_laagste/hoogste/gemiddelde_prijs_vandaag` | Dagstatistieken |
| `sensor.coolblue_energie_start_goedkoopste_blok` | Starttijd van het goedkoopste blok (lengte instelbaar, standaard 3 uur) |
| `binary_sensor.coolblue_energie_in_goedkoopste_blok` | `aan` zolang dat blok loopt |
| `sensor.coolblue_energie_gasprijs` | Gasprijs van gisteren (kosten gedeeld door verbruik), of de vaste reserveprijs |

De entity-ID's hangen af van de taal van je HA. Met Engelse namen heten ze bijvoorbeeld `sensor.coolblue_energie_electricity_price`.

## Acties

```yaml
# Goedkoopste blok voor de vaatwasser, klaar vóór 07:00
action: coolblue_prices.find_cheapest_block
data:
  duration: "02:00:00"
  end_before: "2026-10-09 07:00:00"
response_variable: blok
```

`coolblue_prices.get_prices` (met `kind: consumption` of `feed_in`) geeft alle bekende prijzen terug.

## Prijsinstellingen (Configureren)

- **Wat bevat Coolblue's prijs?**: kies `all-in` als de prijs in HA gelijk is aan die in de
  Coolblue-app. Kies `market` als HA een veel lagere, kale EPEX-prijs toont. In dat geval
  telt de integratie zelf de inkoopvergoeding, energiebelasting en btw erbij op.
- **Inkoopvergoeding**: staat in je contract. Wordt van de terugleverprijs afgetrokken.
- **Energiebelasting**: standaard €0,09161/kWh excl. btw (2026, schijf 1).
- **Vaste gasprijs als reserve**: wordt gebruikt zolang Coolblue geen gasdata van gisteren geeft.

## Testen (ontwikkeling)

```bash
pip install pytest-homeassistant-custom-component beautifulsoup4
pytest
```
