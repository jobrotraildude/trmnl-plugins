#!/usr/bin/env python3
"""Lager innstillingsfeltene til togpluginen med alle togstasjoner som faste valg.

Bruk: python3 lag_tog_skjema.py stasjoner.json plugins/togavganger/form_fields.yml
stasjoner.json lages av stasjoner.py (publiseres på GitHub Pages).
"""
import json, sys
stasjoner = json.load(open(sys.argv[1], encoding="utf-8"))
def q(s): return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'
valg = "\n".join(f"  - {q(k)}: {q(v)}" for d in stasjoner for k, v in d.items())
bio = '''- keyname: author_bio
  field_type: author_bio
  name: Om pluginen
  description: |
    Neste avganger med tog mellom to valgfrie stasjoner i Norge, med sanntid fra <a href="https://entur.no" class="underline">Entur</a>.
    Forsinkelser og innstillinger vises i svart, slik at avvik er det første du ser. Avganger i rute er tegnet tynt og rolig.
    Viser også spor, sporendringer, forventet ankomst, hvor fullt toget pleier å være, og avviksmeldinger fra Bane NOR og togselskapene med full tekst.
    Velg stasjonen du reiser fra og stasjonen du skal til. Vil du se begge retninger, installerer du pluginen to ganger og bytter om stasjonene.
    Alle fire størrelser støttes: hel skjerm, halv bredde, halv høyde og kvart skjerm.
    Data under Norsk lisens for offentlige data (NLOD) fra Entur.
  category: travel
  github_url: https://github.com/jobrotraildude/trmnl-plugins
'''
ut = bio + f'''- keyname: fra_stasjon
  field_type: select
  name: Fra stasjon
  description: Stasjonen du reiser fra.
  indexable: true
  options:
{valg}
- keyname: til_stasjon
  field_type: select
  name: Til stasjon
  description: Stasjonen du skal til. Bare tog som stopper der, vises.
  options:
{valg}
'''
open(sys.argv[2], "w", encoding="utf-8").write(ut)
print(f"Skrev {sys.argv[2]} med {len(stasjoner)} stasjoner")
