# Coolblue Energie Prijzen voor Home Assistant

Custom integration die de dynamische stroomprijzen uit je **eigen Coolblue-account**
haalt (dezelfde bron als de Coolblue-app) en ze als sensoren in Home Assistant zet.

> Coolblue heeft geen officiële API. Deze integratie logt in zoals de website dat doet
> en leest de all-in uurprijzen (incl. belastingen) die het Coolblue Energie-dashboard
> zelf toont. De ongedocumenteerde endpoint `/api/insights` dient als reserve en levert
> de gasgegevens. Als Coolblue het portaal aanpast, kan de integratie breken. De login is overgenomen uit
> [barisdemirdelen/homeassistant-coolblue-energy](https://github.com/barisdemirdelen/homeassistant-coolblue-energy)
> (MIT).

## Eerst testen: `probe.py`

Voordat je de integratie in HA zet, kijk je beter eerst wat Coolblue voor jouw contract teruggeeft:

```bash
cd ~/Claude/Projects/"Coolblue Energy HA"
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

## Grafiek

### ApexCharts Card

Voor een prijsgrafiek van vandaag en morgen gebruik je de
[ApexCharts Card](https://github.com/RomRider/apexcharts-card) (installeren via
**HACS → Frontend**, zoek "apexcharts-card"). Voeg daarna een kaart toe op je dashboard,
kies **Handmatig** en plak:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Stroomprijs
  show_states: true
  colorize_states: true
graph_span: 48h
span:
  start: day
now:
  show: true
  label: Nu
experimental:
  color_threshold: true
yaxis:
  - decimals: 2
    min: ~0
apex_config:
  legend:
    show: false
  tooltip:
    x:
      format: "ddd HH:mm"
series:
  - entity: sensor.coolblue_energie_stroomprijs
    name: Nu
    type: column
    unit: €/kWh
    float_precision: 3
    color_threshold:
      - value: -1
        color: "#2e7d32"
      - value: 0.20
        color: "#f9a825"
      - value: 0.28
        color: "#c62828"
    data_generator: |
      return [
        ...entity.attributes.prices_today,
        ...entity.attributes.prices_tomorrow,
      ].map((p) => [new Date(p.start).getTime(), p.price]);
```

- **Vandaag en morgen:** de grafiek toont 48 uur vanaf middernacht. De prijzen voor
  morgen verschijnen zodra Coolblue ze publiceert (dagelijks vanaf 14:30); tot die tijd
  is de rechterhelft leeg.
- **Kleuren:** groen onder €0,20, oranje tot €0,28, rood daarboven. Pas de grenzen aan
  naar wat voor jou goedkoop en duur is.
- **Entity-ID:** heet je sensor anders (bijvoorbeeld `sensor.coolblue_energie_electricity_price`
  bij een Engelstalige HA), pas dan `entity:` aan.
- **Zonder extra kaart:** de standaard *Geschiedenisgrafiek* met de stroomprijs-sensor
  laat de prijzen uit het verleden zien, maar niet die van de komende uren.

### Plotly Graph Card: vandaag

Wil je een staafgrafiek met kleuren per prijsniveau, de laagste en hoogste prijs van de komende
uren, een stippellijn met de huidige prijs bij "nu" en het lopende uur omlijnd? Gebruik dan de
[Plotly Graph Card](https://github.com/dbuezas/lovelace-plotly-graph-card) (installeren via
**HACS → Frontend**, zoek "plotly"). De kaart toont 6 uur terug en 12 uur vooruit, dus vanaf 14:30
ook de eerste uren van morgen.

```yaml
type: custom:plotly-graph
disable_pinch_to_zoom: true
title: Dynamische stroomprijs
hours_to_show: 18
time_offset: 12h
fn: |
  $fn ({ hass, vars }) => {
    const entity = 'sensor.coolblue_energie_stroomprijs'
    const s = hass.states[entity]
    const prices = [...(s?.attributes?.prices_today ?? []), ...(s?.attributes?.prices_tomorrow ?? [])]
    vars.x = []; vars.y = []; vars.color = []; vars.hover = []
    vars.min = {p: 999, t: null}; vars.max = {p: -999, t: null}
    vars.ymin = 999; vars.ymax = -999
    vars.unit_of_measurement = s?.attributes?.unit_of_measurement ?? '€/kWh'
    vars.now = {t: Date.now(), p: parseFloat(s?.state)}
    vars.now.h = "<b>" + vars.now.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " @now"
    vars.avg = {p: 0, c: 0}
    vars.opacity = []; vars.lw = []
    // Coolblue has no tariff groups: lowest third of prices = low, highest third = high.
    const sorted = prices.map(e => e.price).sort((a, b) => a - b)
    const lowMax = sorted[Math.floor(sorted.length / 3)]
    const highMin = sorted[Math.floor(sorted.length * 2 / 3)]
    const pad = n => String(n).padStart(2, "0")
    prices.forEach(e => {
      const start = new Date(e.start).getTime()
      const end = new Date(e.end).getTime()
      const t = start + (end - start) / 2   // bar in the middle of its hour
      const p = e.price
      vars.avg.p += p
      vars.avg.c++
      const c = p < lowMax ? "#00a964" : p >= highMin ? "#ed5e18" : "#365651"
      if (end > Date.now()) {
        if (p < vars.min.p) vars.min = {p, t, c, h0: new Date(start).getHours()}
        if (p > vars.max.p) vars.max = {p, t, c, h0: new Date(start).getHours()}
      }
      if (p < vars.ymin) vars.ymin = p
      if (p > vars.ymax) vars.ymax = p
      vars.x.push(t)
      vars.y.push(p)
      vars.color.push(c)
      vars.opacity.push(end <= Date.now() ? 0.4 : 1)   // past hours dimmed
      vars.lw.push(start <= Date.now() && Date.now() < end ? 2 : 0)   // outline the current hour
      vars.hover.push(pad(new Date(start).getHours()) + "-" + pad(new Date(end).getHours()) +
        ": <b>" + p.toFixed(3) + "</b> " + vars.unit_of_measurement)
    })
    vars.min.h = "<b>" + vars.min.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " @ " + vars.min.h0 + ":00"
    vars.max.h = "<b>" + vars.max.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " @ " + vars.max.h0 + ":00"
    vars.avg.p = vars.avg.p / vars.avg.c
    vars.avg.h = "<b>" + vars.avg.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " average"
  }
layout:
  dragmode: false
  margin:
    l: 20
    r: 20
    b: 40
  yaxis:
    fixedrange: true
    tickformat: .2f
    range: $fn ({vars}) => [ vars.ymin-0.02, vars.ymax+0.02 ]
    showgrid: false
    visible: false
    showticklabels: true
    showline: false
    title: null
  xaxis:
    fixedrange: true
    tickformat: '%H'
    showgrid: false
    visible: true
    showticklabels: true
    showline: false
    dtick: 3600000
  shapes: >-
    $fn ({vars}) => [{type: 'line', xref: 'x', yref: 'paper', x0: vars.now.t, x1: vars.now.t,
    y0: 0, y1: 1, line: {color: 'gray', width: 1.5, dash: 'dot'}}]
  annotations: >-
    $fn ({vars}) => isNaN(vars.now.p) ? [] : [{text: 'Nu <b>€ ' + vars.now.p.toFixed(3).replace('.', ',') + '</b>',
    xref: 'x', yref: 'paper', x: vars.now.t, y: 1, xanchor: 'left', yanchor: 'top', xshift: 4,
    showarrow: false, font: {size: 13}}]
config:
  displayModeBar: false
  scrollZoom: false
entities:
  - entity: ''
    unit_of_measurement: $ex vars.unit_of_measurement
    showlegend: false
    x: $ex vars.x
    'y': $ex vars.y
    marker:
      color: $ex vars.color
      opacity: $ex vars.opacity
      line:
        color: white
        width: $ex vars.lw
    type: bar
    hovertemplate: $ex vars.hover
  - entity: ''
    mode: markers
    textposition: top
    showlegend: true
    name: $ex vars.min.h
    hovertemplate: $ex vars.min.h
    yaxis: y0
    marker:
      symbol: diamond
      color: $ex vars.min.c
      opacity: 0.7
    x:
      - $ex vars.min.t
    'y':
      - $ex vars.min.p
  - entity: ''
    mode: markers
    textposition: top
    showlegend: true
    name: $ex vars.max.h
    hovertemplate: $ex vars.max.h
    yaxis: y0
    marker:
      symbol: diamond
      color: $ex vars.max.c
      opacity: 0.7
    x:
      - $ex vars.max.t
    'y':
      - $ex vars.max.p
```

### Plotly Graph Card: morgen

Dezelfde stijl, maar alleen voor morgen van 00:00 tot 24:00 (23 of 25 uur bij de wissel van
zomer- naar wintertijd en terug). Laagste en hoogste prijs gelden voor de hele dag. Zolang Coolblue
de prijzen nog niet heeft gepubliceerd, toont de kaart een melding.

```yaml
type: custom:plotly-graph
disable_pinch_to_zoom: true
title: Stroomprijs morgen
hours_to_show: $ex vars.hours
time_offset: $ex vars.offset
fn: |
  $fn ({ hass, vars }) => {
    const entity = 'sensor.coolblue_energie_stroomprijs'
    const s = hass.states[entity]
    const prices = s?.attributes?.prices_tomorrow ?? []
    // Tomorrow 00:00 to the day after 00:00 (23 or 25 hours on DST days).
    const start = new Date(); start.setHours(24, 0, 0, 0)
    const end = new Date(start); end.setDate(end.getDate() + 1)
    vars.hours = Math.round((end - start) / 60000) + "m"
    vars.offset = Math.round((end - Date.now()) / 60000) + "m"
    vars.x = []; vars.y = []; vars.color = []; vars.hover = []
    vars.min = {p: 999, t: null}; vars.max = {p: -999, t: null}
    vars.ymin = 999; vars.ymax = -999
    vars.unit_of_measurement = s?.attributes?.unit_of_measurement ?? '€/kWh'
    vars.avg = {p: 0, c: 0}
    // Coolblue has no tariff groups: lowest third of prices = low, highest third = high.
    const sorted = prices.map(e => e.price).sort((a, b) => a - b)
    const lowMax = sorted[Math.floor(sorted.length / 3)]
    const highMin = sorted[Math.floor(sorted.length * 2 / 3)]
    const pad = n => String(n).padStart(2, "0")
    prices.forEach(e => {
      const t0 = new Date(e.start).getTime()
      const t1 = new Date(e.end).getTime()
      const t = t0 + (t1 - t0) / 2   // bar in the middle of its hour
      const p = e.price
      vars.avg.p += p
      vars.avg.c++
      const c = p < lowMax ? "#00a964" : p >= highMin ? "#ed5e18" : "#365651"
      if (p < vars.min.p) vars.min = {p, t, c, h0: new Date(t0).getHours()}
      if (p > vars.max.p) vars.max = {p, t, c, h0: new Date(t0).getHours()}
      if (p < vars.ymin) vars.ymin = p
      if (p > vars.ymax) vars.ymax = p
      vars.x.push(t)
      vars.y.push(p)
      vars.color.push(c)
      vars.hover.push(pad(new Date(t0).getHours()) + "-" + pad(new Date(t1).getHours()) +
        ": <b>" + p.toFixed(3) + "</b> " + vars.unit_of_measurement)
    })
    vars.available = prices.length > 0
    if (!vars.available) { vars.ymin = 0; vars.ymax = 0.3 }
    vars.min.h = "<b>" + vars.min.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " @ " + vars.min.h0 + ":00"
    vars.max.h = "<b>" + vars.max.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " @ " + vars.max.h0 + ":00"
    vars.avg.p = vars.avg.c ? vars.avg.p / vars.avg.c : NaN
    vars.avg.h = "<b>" + vars.avg.p.toFixed(3) + "</b> " + vars.unit_of_measurement + " average"
  }
layout:
  dragmode: false
  margin:
    l: 20
    r: 20
    b: 40
  yaxis:
    fixedrange: true
    tickformat: .2f
    range: $fn ({vars}) => [ vars.ymin-0.02, vars.ymax+0.02 ]
    showgrid: false
    visible: false
    showticklabels: true
    showline: false
    title: null
  xaxis:
    fixedrange: true
    tickformat: '%H'
    showgrid: false
    visible: true
    showticklabels: true
    showline: false
    dtick: 3600000
  annotations: >-
    $fn ({vars}) => vars.available ? [] : [{text: 'Prijzen voor morgen komen vanaf 14:30',
    xref: 'paper', yref: 'paper', x: 0.5, y: 0.5, showarrow: false, font: {size: 14, color: 'gray'}}]
config:
  displayModeBar: false
  scrollZoom: false
entities:
  - entity: ''
    unit_of_measurement: $ex vars.unit_of_measurement
    showlegend: false
    x: $ex vars.x
    'y': $ex vars.y
    marker:
      color: $ex vars.color
    type: bar
    hovertemplate: $ex vars.hover
  - entity: ''
    mode: markers
    textposition: top
    showlegend: $ex vars.available
    name: $ex vars.min.h
    hovertemplate: $ex vars.min.h
    yaxis: y0
    marker:
      symbol: diamond
      color: $ex vars.min.c
      opacity: 0.7
    x:
      - $ex vars.min.t
    'y':
      - $ex vars.min.p
  - entity: ''
    mode: markers
    textposition: top
    showlegend: $ex vars.available
    name: $ex vars.max.h
    hovertemplate: $ex vars.max.h
    yaxis: y0
    marker:
      symbol: diamond
      color: $ex vars.max.c
      opacity: 0.7
    x:
      - $ex vars.max.t
    'y':
      - $ex vars.max.p
```

Tips voor beide Plotly-kaarten:
- **Kleuren:** Coolblue kent geen tariefgroepen. De kaart verdeelt de getoonde prijzen in drieën:
  het goedkoopste derde is groen, het duurste derde oranje, de rest donkergroen.
- **Entity-ID:** heet je sensor anders, pas dan alleen de regel `const entity = ...` aan.
- **Plakken:** let erop dat `layout:`, `config:` en `entities:` helemaal links beginnen. Verschuift
  de inspringing bij het plakken, dan blijft de kaart leeg. Plak bij twijfel met ⌘⇧V / Ctrl+Shift+V.

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
