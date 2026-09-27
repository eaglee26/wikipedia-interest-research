# Methodology

How `wiki.py research` turns pageviews into verdicts. Thresholds live in
`scripts/wikitrends/config.py` (`THRESHOLDS`); this file explains them.

## Data

- **Source:** Wikimedia Pageviews API (`wikimedia.org/api/rest_v1/metrics/pageviews`),
  daily views per article, `agent=user` (humans; known spiders and heuristically
  detected bots are excluded), `access=all-access` (desktop + mobile web + app).
- **Window:** whole calendar months only. The last month is the latest month whose
  last day is at least 2 days old (a UTC day is published a few hours after it ends).
  Data exists from 2015-07-01.
- **Concept → article:** each topic is resolved to a Wikidata item (QID). Its
  sitelinks give the article title in every language, so all languages measure the
  same concept. Search results are re-ranked by the number of Wikipedia editions
  that have the concept (sitelinks), because Wikidata's own order is not popularity
  (searching "Mercury" lists a car brand before the planet). If two exact matches
  are both widespread, the output marks the topic **ambiguous**.
- **Basket:** a topic can be several concepts. With 2+ languages, only concepts that
  exist in every analysed language are compared ("common basket"); the rest are
  listed as excluded, so languages are compared like for like.
- **Redirects:** when an article's views start late in the window (typically a
  rename), views of its redirect titles are added (`--redirects auto`).
  `--redirects all` always adds them, `none` never does.
- **Normalization:** each language edition's total human views per month
  (`aggregate` endpoint). **Share** = basket views per million views of the same
  edition. Share removes changes that affect the whole edition (e.g. the ~8% drop in
  human pageviews Wikimedia reported for 2025, or Ukrainian Wikipedia's audience
  shifts), so it is the main measure of *interest*. Raw views describe *audience size*.

## Metrics (per language)

| Metric | Definition |
|---|---|
| views/month | average monthly views of the basket over the recent period |
| views change | recent period vs comparison period, raw views |
| share change | same comparison on share (main verdict metric) |
| up months | recent months whose share beats the same month one year earlier |
| trend p | seasonal Kendall test on log(share) (Mann-Kendall if < 24 months) |
| slope %/year | seasonal Theil-Sen slope on log(share) |

**Comparison periods:** 24+ months → last 12 vs previous 12 months. 13-23 months →
last *k* months vs the same *k* months a year earlier (k = n − 12). Under 13 months →
second half vs first half (seasonality not controlled → critical flag).

The seasonal Kendall test compares each calendar month only with the same month in
other years, so school-year or New-Year patterns cannot be mistaken for a trend.
Implementations are validated against `scipy.stats` in `tests/test_stats.py`.

## Direction

Let *c* = share change, threshold 10 %.

- **growing:** c ≥ +10 % and (≥ 8 of 12 months up, or significant positive trend at p < 0.10)
- **declining:** c ≤ −10 % and (≤ 4 of 12 months up, or significant negative trend)
- **stable:** |c| < 10 %
- **mixed:** anything else (the yearly change and the month-by-month picture disagree)

## Trust checks

| Flag | Severity | Rule |
|---|---|---|
| no_article / no_views | critical | no article in this edition, or zero views in the window |
| volume_critical | critical | < 100 views/month |
| volume_warn | warn | < 1,000 views/month |
| too_short | critical | < 13 months of data |
| short_window | warn | 13-23 months |
| spike_driven | critical | spike days carry ≥ 20 % of a period's views AND removing spikes flips or halves the change |
| spikes_present | info | spikes exist but do not change the conclusion |
| late_start | critical/warn | a basket article has no views in the first 2 months (created/renamed); critical if it carries ≥ 20 % of recent views |
| narrow | warn | < 60 % of basket articles move in the basket's direction |
| not_significant | warn | direction is growing/declining but trend p ≥ 0.10 |
| mixed_signals | warn | direction is mixed |
| platform_effect | warn/info | raw views and share point in different directions (warn if opposite) |
| seasonality | info | peak calendar month ≥ 2× the quietest (spikes removed) |

**Spike:** a day with views > max(4 × centered 29-day median, median + 20) and ≥ 20.
"Without spikes" replaces spike days by that median.

## Confidence

- **LOW:** any critical flag, or 3+ warnings
- **MEDIUM:** 1-2 warnings
- **HIGH:** no warnings

Confidence describes how much the *direction verdict* can be trusted. It says
nothing about whether the audience will pay.

## Ranking languages

score = w_volume · scaled(log10 views/month) + w_growth · scaled(share change) +
w_reliability · confidence score (HIGH 1, MEDIUM 0.6, LOW 0.2), where *scaled*
maps the analysed languages to 0-1. Default weights 0.4 / 0.4 / 0.2; users can
change them with `--weights`. Scores are relative to the languages in the run.

## Known data issues

`assets/known-data-issues.json` lists periods when Wikimedia changed how traffic is
classified (e.g. March-August 2025 bot reclassification). Overlapping windows get
a note, and the band is shaded on charts.
