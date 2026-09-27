---
name: wikipedia-interest-research
description: Measure how public interest in topics changes across Wikipedia language editions (Wikimedia pageviews) to decide which topic, course or language market to invest in next. Use when the user asks whether interest in a subject is growing, wants to compare interest between languages, asks which language audiences to research or localize for next, how trustworthy a trend is, or wants charts or a one-page PDF report on topic demand — even if they do not mention Wikipedia or pageviews. Not for writing or summarizing Wikipedia articles, and not for Google Trends or a website's own analytics.
license: MIT
compatibility: Requires Python 3.10+ with uv (recommended) or pip, and internet access to wikimedia.org, wikidata.org and *.wikipedia.org.
metadata:
  author: eaglee26
  version: "0.1.0"
---

# Wikipedia interest research

The bundled CLI does all data work: it finds the right article in every language
(via Wikidata), downloads human pageviews, removes the effect of a whole Wikipedia
edition growing or shrinking, detects spikes and seasonality, rates confidence, ranks
languages, draws charts and builds a one-page PDF. **Your job: turn the request into
one command, read its summary, and answer with its numbers and caveats.**

`SKILL_DIR` below = the folder containing this SKILL.md (shown when the skill loads,
e.g. `.claude/skills/wikipedia-interest-research`). Run commands from the user's
working folder, not from SKILL_DIR; results go to `./wiki-research/`.

## Workflow

1. **Pin down the question.** Topic(s), language editions, period. If languages are
   missing, ask once. Default period: `24m`; for "is this growth real / trustworthy"
   questions use `36m` (more seasons to compare).
2. **Choose the topics** (each becomes one Wikipedia concept):
   - narrow subject ("intermittent fasting"): just that name;
   - broad subject or a product area ("astronomy course", "learning English"): the main
     concept plus 2-5 core related concepts, e.g. `"astronomy, Solar System, black hole,
     telescope, galaxy"`. Tell the user which articles represent the topic.
   - Write names in English when you can; any language works.
3. **Run:**
   ```bash
   uv run SKILL_DIR/scripts/wiki.py research --topics "astronomy, Solar System, black hole" --langs uk --period 36m --ui uk
   ```
   `--langs` takes Wikipedia codes: en de fr es it pt pl cs sk uk ru tr vi id ja ko zh ar
   hi nl sv ro hu el. Use `--ui uk` when the user writes Ukrainian (chart/PDF labels).
4. **Read `CHECK BEFORE ANSWERING`** (top of the output, if present). Every point in it
   must appear in your answer:
   - *ambiguous* topic: if the chosen meaning is wrong, rerun with `--qids Q…`;
   - *no article* in a language: say so plainly — do not guess numbers for it. If the
     output lists a broader concept (proxy), offer it and rerun with `--qids` only if
     the user agrees; always say a proxy measures a broader topic.
5. **Answer** (in the user's language), using only numbers printed by the tool:
   - direction per language (growing / declining / stable / mixed) with the share change,
   - audience size (views/month),
   - confidence (HIGH/MEDIUM/LOW) and its main reason from `WHY`,
   - for comparisons: the `RANKING` and why,
   - 1-2 limitations (e.g. pageviews ≠ willingness to pay; language ≠ country),
   - a concrete next validation step (survey, landing page, ad test in that language).

   **Verify before sending:** save the answer to `answer.md` and run
   `uv run SKILL_DIR/scripts/wiki.py check --run <RUN id> --text answer.md`.
   If it prints `CHECK FAILED`, replace the listed numbers with ones from the output
   (or remove them) and check again. Only send the answer after `CHECK OK`.
6. **PDF, if asked** ("report", "share", "PDF"): copy `SKILL_DIR/assets/narrative.template.json`
   to `./narrative.json`, replace the four texts (same language as the user), then:
   ```bash
   uv run SKILL_DIR/scripts/wiki.py report --run <RUN id from output> --narrative narrative.json --ui uk
   ```
   If it prints `REPORT NOT BUILT`, fix exactly what it lists and rerun the same command.
   Give the user the printed PDF path. Charts are also saved as PNG in the run folder.

## Follow-up questions

Rerun `research` with changed flags — cached data makes it fast. Then compare with
`uv run SKILL_DIR/scripts/wiki.py diff <old run> <new run>` and say what changed.

| User says | Change |
|---|---|
| add / remove a language | `--langs` |
| longer / shorter / specific period | `--period 5y` or `--start 2022-01 --end 2025-12` |
| "growth matters more than size" | `--weights growth=0.6,volume=0.2,reliability=0.2` |
| drop an article from the topic | `--exclude "telescope"` |
| wrong meaning of a word | `--qids Q308` (take the id from the output) |
| "what did we find before?" | `uv run SKILL_DIR/scripts/wiki.py runs` |

## Gotchas

- Never write your own code to call Wikimedia APIs or to compute trends: the CLI already
  handles caching, rate limits, redirects, spikes and normalization.
- Do not compute dates, percentages or differences yourself; the output has them. To
  double-check a written answer: `wiki.py check --run <id> --text answer.md`.
- Country codes are not language codes: Czech is `cs` (not cz), Ukrainian `uk` (not ua),
  Greek `el`, Japanese `ja`, Swedish `sv`, Danish `da`.
- "Views" are page views, not people. Say "переглядів"/"views", never "users" or
  population numbers.
- Say "Polish-language Wikipedia", not "Poland": a language edition is not a country.
- A shrinking raw count is not lost interest by itself: Wikipedia traffic falls overall.
  Judge interest by **SHARE CHG** (normalized); mention VIEWS CHG as audience size change.
- LOW confidence is a finding, not a failure: report it with its reason.

## Errors

Exit code 2 = bad arguments (message says the fix) · 4 = no network access to Wikimedia
(run `wiki.py doctor`, tell the user) · 5 = topic or run not found (try another name or
`--qids`) · 3 = text/report failed validation (fix what is listed).

## More detail (read only when needed)

- How metrics, checks and confidence work, or the user asks "why this confidence?":
  `SKILL_DIR/references/methodology.md`
- How to phrase recommendations, proxies and comparisons; answer examples:
  `SKILL_DIR/references/interpretation.md`
- API limits, `doctor` failures, SSL/proxy problems: `SKILL_DIR/references/api-notes.md`
