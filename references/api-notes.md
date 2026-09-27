# API notes and troubleshooting

## Endpoints used

| Purpose | Endpoint |
|---|---|
| daily views of an article | `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/user/{Title_With_Underscores}/daily/{YYYYMMDD}/{YYYYMMDD}` |
| monthly total of an edition | `.../pageviews/aggregate/{lang}.wikipedia/all-access/user/monthly/{YYYYMMDD}/{YYYYMMDD}` |
| concept search | `https://www.wikidata.org/w/api.php?action=wbsearchentities` |
| popularity (sitelink count) | `action=query&prop=pageprops&ppprop=wb-sitelinks` on Wikidata |
| titles per language | `action=wbgetentities&props=sitelinks|labels|descriptions&sitefilter=...` |
| broader concepts (proxies) | `action=wbgetclaims` for P279 / P361 / P31 |
| redirect titles | `https://{lang}.wikipedia.org/w/api.php?action=query&prop=redirects` |

## Quirks the code already handles

- **User-Agent is mandatory in practice.** Since 2026 Wikimedia rate-limits clients by
  identity: unidentified clients get ~10 requests/minute, clients with a User-Agent of
  the form `name/version (contact)` ~200. The CLI sends such a header (contact from
  `WIKI_RESEARCH_CONTACT` or the default repo URL) and throttles itself to 150/min.
- **429 / 5xx** are retried with exponential backoff, honouring `Retry-After`.
- **404 from per-article** means "no data" (article did not exist or had zero views),
  not an error. Days with zero views are simply absent from responses; the cache
  records fetched ranges so absent days count as 0.
- **Titles:** spaces → underscores, then URL-encoded (including `/`).
- **Redirect/rename views** are counted under the redirect title, not the target.
- **Monthly windows** use whole months only; the current month is never used.
- **Cache:** `~/.cache/wikipedia-interest-research/cache.sqlite3` (override with
  `WIKI_RESEARCH_CACHE`). Past days are cached forever; Wikidata lookups for 14 days.
  Delete the file to start fresh.

## `wiki.py doctor` failures

| Symptom | Fix |
|---|---|
| `FAIL network` with 403/407 or "Cannot reach" | the machine or sandbox blocks wikimedia.org / wikidata.org; allow these hosts or run elsewhere |
| `CERTIFICATE_VERIFY_FAILED` | python.org Python on macOS: run "Install Certificates.command", or use `uv run` (bundles certifi) |
| `Missing dependency` | use `uv run SKILL_DIR/scripts/wiki.py …` or `python3 -m pip install -r SKILL_DIR/requirements.txt` |
| cache not writable | set `WIKI_RESEARCH_CACHE` to a writable folder |
| repeated 429 | another process uses the same IP; wait a minute; lower `WIKI_RESEARCH_RATE_PER_MIN` |

## Environment variables

| Variable | Meaning |
|---|---|
| `WIKI_RESEARCH_CONTACT` | contact URL/email for the User-Agent |
| `WIKI_RESEARCH_OUT` | default output folder (instead of `./wiki-research`) |
| `WIKI_RESEARCH_CACHE` | cache folder |
| `WIKI_RESEARCH_RATE_PER_MIN` | self-imposed request rate (default 150) |
| `WIKI_RESEARCH_TODAY` | pin "today" (YYYY-MM-DD) for reproducible reruns/tests |
