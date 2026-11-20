#!/usr/bin/env python3
"""Lager stasjoner.json: alle togstasjoner i Norge fra Entur, i formatet TRMNLs xhrSelect-felt forventer.

Resultat: [{"Oslo S": "NSR:StopPlace:337"}, {"Lillehammer": "NSR:StopPlace:…"}, ...] sortert alfabetisk.
Bruk: python stasjoner.py --ut site/stasjoner.json
Kun standardbiblioteket.
"""
import argparse, json, locale, os, sys, urllib.request

KLIENT = "trmnl-plugins-stasjonsliste"
SPORRING = """{ stopPlacesByBbox(minimumLatitude: 57.5, maximumLatitude: 71.5, minimumLongitude: 4.0, maximumLongitude: 31.5, filterByInUse: true) { id name transportMode } }"""


def hent():
    req = urllib.request.Request(
        "https://api.entur.io/journey-planner/v3/graphql",
        data=json.dumps({"query": SPORRING}).encode(),
        headers={"Content-Type": "application/json", "ET-Client-Name": KLIENT},
    )
    with urllib.request.urlopen(req, timeout=90) as svar:
        return json.loads(svar.read().decode("utf-8"))


def er_tog(modus):
    if isinstance(modus, list):
        return "rail" in modus
    return modus == "rail"


def kortnavn(navn):
    # Entur kaller mange stasjoner «Lillehammer stasjon». Pluginen legger selv til «stasjon» der det passer.
    return navn[:-len(" stasjon")] if navn.endswith(" stasjon") else navn


def sorteringsnokkel(navn):
    # Norsk rekkefølge: Æ, Ø, Å sist
    tabell = str.maketrans({"Æ": "{", "æ": "{", "Ø": "|", "ø": "|", "Å": "}", "å": "}"})
    return navn.lower().translate(tabell)


def bygg(svar):
    steder = (svar.get("data") or {}).get("stopPlacesByBbox") or []
    sett = {}
    for s in steder:
        if not s or not er_tog(s.get("transportMode")) or not s.get("id") or not s.get("name"):
            continue
        sett.setdefault(kortnavn(s["name"]), s["id"])
    return [{navn: sett[navn]} for navn in sorted(sett, key=sorteringsnokkel)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ut", default="site/stasjoner.json")
    arg = p.parse_args()
    liste = bygg(hent())
    if len(liste) < 100:
        sys.exit(f"Fikk bare {len(liste)} togstasjoner fra Entur – skriver ikke filen.")
    os.makedirs(os.path.dirname(arg.ut) or ".", exist_ok=True)
    with open(arg.ut, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Skrev {arg.ut}: {len(liste)} togstasjoner")


if __name__ == "__main__":
    main()
