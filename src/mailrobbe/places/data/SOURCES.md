# Places data

The lists the step places and the places API read (`mailrobbe.places.gazetteer`, D242 to D244),
built by `scripts/places_data.py` from the files below, downloaded on 2026-10-22. Run the script to
refresh them; a new build changes `places_version()`, and the next import run gives every place
entity and invitation its point again.

## towns.tsv.gz (46585 towns)

GeoNames `cities500.zip` for Germany, Austria, Switzerland and Liechtenstein: every populated
place of at least 500 inhabitants and every seat of an administrative unit (PPLA to
PPLA5, PPLC) whatever its size; GeoNames `cities15000.zip` for every other country. Sections of
towns, historical, destroyed and abandoned places (PPLX, PPLH, PPLW, PPLQ, PPLCH) are left out.
Most populous first.

- name: its own where it is one of its German names in `alternateNamesV2.zip` (isolanguage de,
  not colloquial or historic), else the German spelling of it (Chişinău for Chisinau), else the
  German name GeoNames prefers, else its own; local: its own where that differs (Munich for
  München)
- region: the first administrative level (`admin1CodesASCII.txt`), by its short German name
  where GeoNames has one
- names: GeoNames' alternatenames in Latin script, capitalised, without numbers, airport and
  other codes; spellings that differ only in case, accents or punctuation once

## postcodes.tsv.gz (38614 rows)

GeoNames postal codes `DE.zip`, `AT.zip`, `CH.zip`, `LI.zip`: one row per postcode and place
name with its point; names of PO boxes and districts cut to the town (Bern 15, Wien, Innere
Stadt), large customers (companies) left out; the region as in `towns.tsv.gz`.

## countries.tsv (243 countries)

Natural Earth 1:10m `admin_0_countries` (version 5.1.1): every country or territory with an
ISO 3166-1 alpha-2 code (ISO_A2_EH), its label point (LABEL_Y, LABEL_X), the German name
(NAME_DE; Zypern, Taiwan, China, Kaimaninseln and Moldau instead of its long forms), the English
name and the long forms; England, Schottland, Wales and Nordirland from `admin_0_map_units`
with their ISO 3166-2 codes.

## country_names.txt and town_names.txt

Written by hand: the names of countries texts use that Natural Earth does not list (Holland,
USA, Weißrussland), and of towns that GeoNames does not list, each for a name of the lists
(Kischinau for Chişinău, Rapperswil-Jona for Rapperswil SG).

## Sources and licences

- GeoNames, <https://www.geonames.org/>, licensed under CC BY 4.0
  (<https://creativecommons.org/licenses/by/4.0/>):
  https://download.geonames.org/export/dump/cities500.zip, https://download.geonames.org/export/dump/cities15000.zip,
  https://download.geonames.org/export/dump/admin1CodesASCII.txt, https://download.geonames.org/export/dump/alternateNamesV2.zip,
  https://download.geonames.org/export/zip/ (DE.zip, AT.zip, CH.zip, LI.zip).
- Natural Earth, <https://www.naturalearthdata.com/>, public domain:
  https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip, https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_map_units.zip.
