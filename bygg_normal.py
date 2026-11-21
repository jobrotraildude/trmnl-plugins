#!/usr/bin/env python3
"""Er været normalt? – bygger normal.json for TRMNL-pluginen.

Henter døgnverdier (middel, maks, min) fra MET Frost for én værstasjon, lagrer hele
historikken i en CSV-fil i repoet, og regner ut hvordan de siste dagene ligger an mot
det som er vanlig for datoen. Dagens verdi og varselet videre kommer fra timesmålinger
(Frost) og MET Locationforecast.

Bruk:
    FROST_CLIENT_ID=... FROST_STASJON=SNxxxxx python bygg_normal.py --cache data/frost_doegn.csv --ut site/normal.json

Stasjonen og posisjonen leses fra miljøvariabler (GitHub-secrets), så de står ikke i koden.
Stedsnavn og stasjons-ID skrives heller ikke til normal.json.

Kun standardbiblioteket – ingen pip install nødvendig.
"""
import argparse
import base64
import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

# ----------------------------------------------------------------------------- innstillinger
STASJON = os.environ.get("FROST_STASJON", "").strip()   # Frost-stasjon, f.eks. SN18700. Settes som secret.
FORSTE_AAR = 1874              # første år vi prøver å hente (tomme år hoppes over)
NORMAL_FRA, NORMAL_TIL = 1991, 2020   # gjeldende klimanormal: gir snitt og normalbåndet
DAGER_TILBAKE = 60             # hvor langt tilbake kurven går
DAGER_FRAM = 7                 # dager med varsel til høyre for i dag
VINDU = 7                      # ± dager rundt datoen som brukes til snitt og normalbånd
REKORDVINDU = 2                # ± dager rundt datoen for rekordspennet i kurven
NEDRE, OVRE = 10, 90           # prosentiler for «normalt» (de midterste 80 % av årene)
UVANLIG_NEDRE, UVANLIG_OVRE = 2.5, 97.5   # utenfor disse kalles dagen «uvanlig»
BRUKERAGENT = "trmnl-plugins/1.0 github.com/jobrotraildude/trmnl-plugins"
TIDSSONE = ZoneInfo("Europe/Oslo")

ELEMENTER = {
    "middel": "mean(air_temperature P1D)",
    "maks": "max(air_temperature P1D)",
    "min": "min(air_temperature P1D)",
}
# Frost kan levere samme døgnverdi med flere tidsforskyvninger. Rekkefølgen under er METs
# anbefalte: middel regnes 00–00 UTC, maks og min over standarddøgnet som ender 18 UTC.
OFFSET_VALG = {
    "middel": ["PT0H", "PT6H", "PT18H"],
    "maks": ["PT18H", "PT0H", "PT6H"],
    "min": ["PT18H", "PT0H", "PT6H"],
}
NOKLER = ["middel", "maks", "min"]
MND = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"]
MND_KORT = ["jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"]
UKEDAG = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]


# ----------------------------------------------------------------------------- henting
def hent_json(url, headers):
    """Henter en URL og returnerer JSON. Returnerer None når Frost svarer «ingen data» (404/412)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as svar:
            return json.loads(svar.read().decode("utf-8"))
    except urllib.error.HTTPError as feil:
        if feil.code in (404, 412):
            return None
        raise


def frost(endepunkt, params, klient_id):
    url = "https://frost.met.no/" + endepunkt + "?" + urllib.parse.urlencode(params)
    token = base64.b64encode((klient_id + ":").encode()).decode()
    svar = hent_json(url, {"Authorization": "Basic " + token, "User-Agent": BRUKERAGENT})
    return (svar or {}).get("data", [])


def hent_doegn(fra, til, klient_id):
    """Døgnverdier fra Frost for [fra, til). Returnerer {dato: {"middel": x, "maks": y, "min": z}}."""
    rader = frost("observations/v0.jsonld", {
        "sources": STASJON,
        "elements": ",".join(ELEMENTER.values()),
        "referencetime": f"{fra.isoformat()}/{til.isoformat()}",
    }, klient_id)
    navn = {v: k for k, v in ELEMENTER.items()}
    valgt = {}  # (dato, nøkkel) -> (rang, verdi)
    for rad in rader:
        dato = dt.date.fromisoformat(rad["referenceTime"][:10])
        for obs in rad.get("observations", []):
            nokkel = navn.get(obs.get("elementId"))
            if nokkel is None or obs.get("value") is None:
                continue
            offset = obs.get("timeOffset", "PT0H")
            rang = OFFSET_VALG[nokkel].index(offset) if offset in OFFSET_VALG[nokkel] else 99
            if (dato, nokkel) not in valgt or rang < valgt[(dato, nokkel)][0]:
                valgt[(dato, nokkel)] = (rang, float(obs["value"]))
    ut = {}
    for (dato, nokkel), (_, verdi) in valgt.items():
        ut.setdefault(dato, {})[nokkel] = verdi
    return ut


def hent_timer(fra, til, klient_id):
    """Timesmålinger av lufttemperatur fra Frost. Returnerer {utc-time: verdi}."""
    rader = frost("observations/v0.jsonld", {
        "sources": STASJON,
        "elements": "air_temperature",
        "timeresolutions": "PT1H",
        "referencetime": f"{fra.isoformat()}/{til.isoformat()}",
    }, klient_id)
    ut = {}
    for rad in rader:
        tid = dt.datetime.fromisoformat(rad["referenceTime"].replace("Z", "+00:00")).replace(minute=0, second=0, microsecond=0)
        for obs in rad.get("observations", []):
            if obs.get("elementId") == "air_temperature" and obs.get("value") is not None:
                ut[tid] = float(obs["value"])
    return ut


def hent_posisjon(klient_id):
    try:
        rader = frost("sources/v0.jsonld", {"ids": STASJON}, klient_id)
        lon, lat = rader[0]["geometry"]["coordinates"][:2]
        return round(lat, 4), round(lon, 4)
    except Exception:
        lat, lon = os.environ.get("HOME_LAT"), os.environ.get("HOME_LON")
        return (float(lat), float(lon)) if lat and lon else (None, None)


def hent_varsel(lat, lon):
    """Timesverdier fra MET Locationforecast, lineært interpolert der varselet har grovere steg."""
    if lat is None or lon is None:
        return {}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"
    svar = hent_json(url, {"User-Agent": BRUKERAGENT}) or {}
    punkter = []
    for steg in svar.get("properties", {}).get("timeseries", []):
        temp = steg.get("data", {}).get("instant", {}).get("details", {}).get("air_temperature")
        if temp is not None:
            punkter.append((dt.datetime.fromisoformat(steg["time"].replace("Z", "+00:00")), float(temp)))
    ut = {}
    for (t0, v0), (t1, v1) in zip(punkter, punkter[1:]):
        timer = int((t1 - t0).total_seconds() // 3600)
        for k in range(max(timer, 1)):
            ut[t0 + dt.timedelta(hours=k)] = v0 + (v1 - v0) * k / max(timer, 1)
    if punkter:
        ut[punkter[-1][0]] = punkter[-1][1]
    return ut


# ----------------------------------------------------------------------------- lokal historikk
def les_cache(sti):
    data = {}
    if os.path.exists(sti):
        with open(sti, newline="", encoding="utf-8") as f:
            for rad in csv.DictReader(f):
                verdier = {k: float(rad[k]) for k in NOKLER if rad.get(k) not in (None, "")}
                if verdier:
                    data[dt.date.fromisoformat(rad["dato"])] = verdier
    return data


def skriv_cache(sti, data):
    os.makedirs(os.path.dirname(sti) or ".", exist_ok=True)
    with open(sti, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dato"] + NOKLER)
        for dato in sorted(data):
            w.writerow([dato.isoformat()] + ["" if data[dato].get(k) is None else f"{data[dato][k]:.1f}" for k in NOKLER])


def oppdater_cache(data, klient_id, i_dag):
    """Første kjøring henter hele historikken i femårsbolker. Senere hentes bare de siste 120 dagene."""
    if not data:
        print(f"Tom historikk – henter alt fra {FORSTE_AAR}. Dette tar et par minutter.")
        for aar in range(FORSTE_AAR, i_dag.year + 1, 5):
            ny = hent_doegn(dt.date(aar, 1, 1), min(dt.date(aar + 5, 1, 1), i_dag + dt.timedelta(days=1)), klient_id)
            print(f"  {aar}–{aar + 4}: {len(ny)} døgn")
            data.update(ny)
    else:
        ny = hent_doegn(i_dag - dt.timedelta(days=120), i_dag + dt.timedelta(days=1), klient_id)
        for dato, verdier in ny.items():
            data.setdefault(dato, {}).update(verdier)
    return data


# ----------------------------------------------------------------------------- statistikk
def prosentil(sortert, p):
    if not sortert:
        return None
    pos = (len(sortert) - 1) * p / 100
    lav = int(pos)
    hoy = min(lav + 1, len(sortert) - 1)
    return sortert[lav] + (sortert[hoy] - sortert[lav]) * (pos - lav)


def samme_dato(aar, dato):
    try:
        return dt.date(aar, dato.month, dato.day)
    except ValueError:          # 29. februar i et år uten skuddår
        return dt.date(aar, 3, 1)


def utvalg(hist, nokkel, dato, aar_fra, aar_til, vindu, for_dato):
    """Alle historiske verdier innen ± vindu dager fra datoen, i årene [aar_fra, aar_til], før for_dato."""
    ut = []
    for aar in range(aar_fra, aar_til + 1):
        midt = samme_dato(aar, dato)
        for k in range(-vindu, vindu + 1):
            d = midt + dt.timedelta(days=k)
            if d < for_dato and nokkel in hist.get(d, {}):
                ut.append((hist[d][nokkel], d))
    return ut


def klima(hist, nokkel, dato, for_dato):
    """Snitt, normalbånd og rekordspenn for én dato."""
    normal = sorted(v for v, _ in utvalg(hist, nokkel, dato, NORMAL_FRA, NORMAL_TIL, VINDU, for_dato))
    alle = utvalg(hist, nokkel, dato, FORSTE_AAR, for_dato.year, REKORDVINDU, for_dato)
    if len(normal) < 30 or not alle:
        return None
    return {
        "snitt": sum(normal) / len(normal),
        "lav": prosentil(normal, NEDRE),
        "hoy": prosentil(normal, OVRE),
        "min": min(v for v, _ in alle),
        "maks": max(v for v, _ in alle),
        "utvalg": normal,
    }


def doegn_fra_timer(timer, dato):
    """Døgnverdier ut fra timesverdier, med samme døgndefinisjon som døgnverdiene fra Frost:
    middel over UTC-døgnet 00–24, maks og min over klimadøgnet 18–18 UTC som ender på datoen.
    Krever minst 20 av 24 timer i hvert vindu. Returnerer bare verdiene som har nok timer."""
    def vindu(start):
        tider = (start + dt.timedelta(hours=h) for h in range(24))
        return [timer[t] for t in tider if t in timer]

    midnatt = dt.datetime(dato.year, dato.month, dato.day, tzinfo=dt.timezone.utc)
    utc_doegn = vindu(midnatt)
    klimadoegn = vindu(midnatt - dt.timedelta(hours=6))  # fra kl. 18 UTC dagen før
    ut = {}
    if len(utc_doegn) >= 20:
        ut["middel"] = sum(utc_doegn) / len(utc_doegn)
    if len(klimadoegn) >= 20:
        ut["maks"], ut["min"] = max(klimadoegn), min(klimadoegn)
    return ut or None


# ----------------------------------------------------------------------------- tekst
def tall(v, tegn=False):
    s = f"{abs(v):.1f}".replace(".", ",")
    if round(v, 1) < 0:
        return "−" + s
    return ("+" + s) if tegn and round(v, 1) > 0 else s


def tid_paa_maaneden(dato):
    del_ = "begynnelsen" if dato.day <= 10 else ("midten" if dato.day <= 20 else "slutten")
    return f"{del_} av {MND[dato.month - 1]}"


def vurder(verdi, kl, dato):
    """Lager dom, forklaring og merkelapper for én verdi mot klimaet for datoen."""
    sommer = 5 <= dato.month <= 9
    varm, kald = ("varmt", "kjølig") if sommer else ("mildt", "kaldt")
    varmere, kaldere = ("Varmere", "Kjøligere") if sommer else ("Mildere", "Kaldere")
    utv = kl["utvalg"]
    pst = 100 * sum(1 for v in utv if v < verdi) / len(utv)
    naar = tid_paa_maaneden(dato)
    if verdi > kl["maks"]:
        klasse, dom, kort = 3, f"Rekord{varm}", f"rekord{varm[:-1]}"
        setning = f"{varmere} enn noen måling for {naar}"
    elif verdi < kl["min"]:
        klasse, dom, kort = -3, f"Rekord{kald}", f"rekord{kald[:-1] if kald.endswith('t') else kald}"
        setning = f"{kaldere} enn noen måling for {naar}"
    elif pst > UVANLIG_OVRE:
        klasse, dom, kort = 2, f"Uvanlig {varm}", f"uvanlig {varm[:-1]}"
        setning = f"{varmere} enn nesten alle dager i {naar}"
    elif pst > OVRE:
        klasse, dom, kort = 1, f"{varmere} enn normalt", varm[:-1]
        setning = f"{varmere} enn {min(9, round(pst / 10))} av 10 dager i {naar}"
    elif pst < UVANLIG_NEDRE:
        klasse, dom, kort = -2, f"Uvanlig {kald}", f"uvanlig {kald[:-1] if kald.endswith('t') else kald}"
        setning = f"{kaldere} enn nesten alle dager i {naar}"
    elif pst < NEDRE:
        klasse, dom, kort = -1, f"{kaldere} enn normalt", kald[:-1] if kald.endswith("t") else kald
        setning = f"{kaldere} enn {min(9, round((100 - pst) / 10))} av 10 dager i {naar}"
    else:
        klasse, dom, kort = 0, "Normalt for årstiden", "normal"
        setning = f"Omtrent som vanlig for {naar}"
    avvik = verdi - kl["snitt"]
    retning = "over" if avvik > 0 else "under"
    avvik_tekst = "Som normalen" if abs(round(avvik, 1)) < 0.05 else f"{tall(abs(avvik))}° {retning} normalen"
    return {
        "verdi": tall(verdi) + "°",
        "normal": tall(kl["snitt"]) + "°",
        "avvik": tall(avvik, tegn=True) + "°",
        "avvik_tekst": avvik_tekst,
        "normal_spenn": f"{tall(kl['lav'])} til {tall(kl['hoy'])}°",
        "dom": dom,
        "kort": kort,
        "setning": setning,
        "klasse": klasse,
        "utenfor": klasse != 0,
        "prosentil": round(pst),
    }


def rekord_for_dato(hist, nokkel, dato, for_dato):
    alle = utvalg(hist, nokkel, dato, FORSTE_AAR, for_dato.year, 0, for_dato)
    if not alle:
        return {}
    hoy, lav = max(alle), min(alle)
    return {
        "rekord_hoy": tall(hoy[0]) + "°", "rekord_hoy_aar": hoy[1].year,
        "rekord_lav": tall(lav[0]) + "°", "rekord_lav_aar": lav[1].year,
    }


# ----------------------------------------------------------------------------- hovedløp
def bygg(hist, timer, i_dag, naa):
    start = i_dag - dt.timedelta(days=DAGER_TILBAKE)
    datoer = [start + dt.timedelta(days=i) for i in range(DAGER_TILBAKE + DAGER_FRAM + 1)]
    i_t = DAGER_TILBAKE
    serie = {k: {f: [] for f in ("t", "snitt", "lav", "hoy", "min", "maks")} for k in NOKLER}
    klima_i_dag, verdi_i_dag = {}, {}

    for i, dato in enumerate(datoer):
        faktisk = hist.get(dato, {}) if dato < i_dag else {}
        estimat = doegn_fra_timer(timer, dato) or {}
        for k in NOKLER:
            kl = klima(hist, k, dato, start)
            # Målt døgnverdi brukes når den finnes. Ellers timesmålinger så langt + varsel.
            verdi = faktisk.get(k, estimat.get(k))
            s = serie[k]
            s["t"].append(None if verdi is None else round(verdi, 1))
            for felt in ("snitt", "lav", "hoy", "min", "maks"):
                s[felt].append(None if kl is None else round(kl[felt], 1))
            if i == i_t:
                klima_i_dag[k], verdi_i_dag[k] = kl, verdi

    ut = {
        "oppdatert": naa.astimezone(TIDSSONE).strftime("%d.%m kl. %H:%M"),
        "dato_tekst": f"{UKEDAG[i_dag.weekday()]} {i_dag.day}. {MND[i_dag.month - 1]}",
        "dato_kort": f"{i_dag.day}. {MND_KORT[i_dag.month - 1]}",
        "normalperiode": f"{NORMAL_FRA}–{NORMAL_TIL}",
        "band_pst": OVRE - NEDRE,
        "rekord_fra": min((d.year for d in hist), default=FORSTE_AAR),
        "har_data": True,
    }
    for k in NOKLER:
        if klima_i_dag[k] is None or verdi_i_dag[k] is None:
            ut[k] = {"mangler": True}
            ut["har_data"] = ut["har_data"] and k != "middel"
            continue
        ut[k] = vurder(verdi_i_dag[k], klima_i_dag[k], i_dag)
        ut[k].update(rekord_for_dato(hist, k, i_dag, start))

    # Siste 30 dager (til og med i dag) mot normalen, for døgnmiddel
    s = serie["middel"]
    par = [(s["t"][i], s["snitt"][i], s["lav"][i], s["hoy"][i]) for i in range(i_t - 29, i_t + 1)
           if s["t"][i] is not None and s["snitt"][i] is not None]
    if par:
        avvik = sum(t - m for t, m, _, _ in par) / len(par)
        over = sum(1 for t, _, _, h in par if t > h)
        under = sum(1 for t, _, l, _ in par if t < l)
        ut["siste30"] = {"avvik": tall(avvik, tegn=True) + "°", "over": over, "under": under, "dager": len(par)}
    else:
        ut["siste30"] = {"avvik": "–", "over": 0, "under": 0, "dager": 0}

    # Selve kurvedataene legges som én ferdig tekststreng, så pluginen kan skrive den rett inn i et script
    ut["serie"] = json.dumps({"d0": start.isoformat(), "n": len(datoer), "iT": i_t, **serie}, separators=(",", ":"))
    return ut


def dekning(hist):
    tiaar = {}
    for dato, v in hist.items():
        if "middel" in v:
            tiaar[dato.year // 10 * 10] = tiaar.get(dato.year // 10 * 10, 0) + 1
    print("Døgnmiddel per tiår:", ", ".join(f"{t}-tallet: {n}" for t, n in sorted(tiaar.items())))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="data/frost_doegn.csv")
    p.add_argument("--ut", default="docs/normal.json")
    arg = p.parse_args()
    klient_id = os.environ.get("FROST_CLIENT_ID")
    if not klient_id:
        sys.exit("Mangler FROST_CLIENT_ID (legg den som secret i GitHub).")
    if not STASJON:
        sys.exit("Mangler FROST_STASJON (legg den som secret i GitHub).")

    naa = dt.datetime.now(dt.timezone.utc)
    i_dag = naa.astimezone(TIDSSONE).date()

    hist = oppdater_cache(les_cache(arg.cache), klient_id, i_dag)
    if not hist:
        sys.exit("Fikk ingen døgnverdier fra Frost. Sjekk FROST_STASJON og FROST_CLIENT_ID.")
    skriv_cache(arg.cache, hist)
    dekning(hist)

    lat, lon = hent_posisjon(klient_id)
    timer = hent_varsel(lat, lon)
    timer.update(hent_timer(i_dag - dt.timedelta(days=4), i_dag + dt.timedelta(days=1), klient_id))  # målinger overstyrer varsel

    ut = bygg(hist, timer, i_dag, naa)
    os.makedirs(os.path.dirname(arg.ut) or ".", exist_ok=True)
    with open(arg.ut, "w", encoding="utf-8") as f:
        json.dump(ut, f, ensure_ascii=False, indent=1)
    print(f"Skrev {arg.ut}: {ut['dato_tekst']} – {ut['middel'].get('dom', 'mangler data')} ({ut['middel'].get('verdi', '–')})")


if __name__ == "__main__":
    main()
