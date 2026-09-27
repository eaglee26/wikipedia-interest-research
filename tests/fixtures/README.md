# Test fixtures

Files named `real_*` are genuine API responses captured on 2026-09-27 from
wikimedia.org (Pageviews API), wikidata.org and *.wikipedia.org (Action API)
via a browser, then saved verbatim (large Wikidata search results trimmed to
the fields the code reads). They let the tests run without network access
while still exercising real response shapes, real titles with diacritics,
real 404 bodies and real traffic patterns (a one-day spike, school-year
seasonality, a shrinking wiki).

Notable facts these fixtures pin down:
- Polish Wikipedia has no article for "intermittent fasting" (Q1666254 has no
  plwiki sitelink; direct title lookups return `missing`).
- Czech "Přerušovaný půst" had a one-day spike on 2025-04-14 (508 of 958
  April views).
- Ukrainian "Астрономія" peaks every September (school year).
- Wikidata search for "Mercury" returns the car brand first; ranking by
  sitelink count must pick the planet (Q308) and flag the element (Q925).
