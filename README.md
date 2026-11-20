# trmnl-plugins

Data og skjermer for [TRMNL](https://trmnl.com), bygget av en GitHub Action og publisert på GitHub Pages. Ingen egen server.

## Hva som publiseres

Alt ligger på `https://jobrotraildude.github.io/trmnl-plugins/`.

| Fil | Brukes av | Data | Oppdateres |
|---|---|---|---|
| `quakes.png` | Jordskjelv (Image Display) | USGS, skjelv M2,5+ siste døgn | hver halvtime |
| `volcanoes.png` | Vulkaner (Image Display) | Smithsonian/USGS Weekly Volcanic Activity Report | hver halvtime |
| `normal.json` | Er været normalt? og Døgnets spenn | MET Frost og MET Locationforecast | hver halvtime |
| `stasjoner.json` | Togavganger (nedtrekkslistene) | Entur | én gang i uka |

## Mapper
- `render.py`, `volcanoes.json` – tegner jordskjelv- og vulkanskjermene
- `bygg_normal.py` – henter temperaturhistorikk fra Frost og regner ut hva som er normalt
- `stasjoner.py` – lager listen over togstasjoner
- `plugins/` – markup og innstillingsfelt til TRMNL-pluginene
- `.github/workflows/bygg.yml` – kjører alt og publiserer

## Oppsett

1. **Secrets** under *Settings → Secrets and variables → Actions*:
   - `FROST_CLIENT_ID` – gratis klient-ID fra [frost.met.no](https://frost.met.no)
   - `FROST_STASJON` – Frost-stasjonen temperaturene hentes fra, for eksempel `SN18700`
   - `HOME_LAT`, `HOME_LON` – posisjon for «nærmest deg» på jordskjelvskjermen og for værvarselet
2. **Pages:** *Settings → Pages → Source:* **GitHub Actions**.
3. **Kjør:** *Actions → Bygg TRMNL-data → Run workflow.*

Posisjon og stasjon leses fra secrets og står ikke i koden. Frost-historikken mellomlagres i GitHubs cache og committes ikke.

## Lisens og data
Værdata fra MET Norge (CC BY 4.0 / NLOD). Stasjonsdata fra Entur (NLOD). Jordskjelv fra USGS, vulkaner fra Smithsonian Institution Global Volcanism Program. Fonter: Space Grotesk og IBM Plex Mono (SIL Open Font License).
