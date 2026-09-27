# Interpreting results

Read this when writing a recommendation, handling missing articles or proxies, or
when the user challenges a conclusion.

## What the numbers can and cannot say

- **Pageviews = curiosity on Wikipedia.** They are a lead for what to validate next,
  not proof of demand or willingness to pay. Say this once, briefly.
- **Share change** answers "is interest in this topic rising relative to everything
  else people read in this language?". **Views change** answers "is the reachable
  Wikipedia audience for it growing?". When they disagree, report both: e.g. "views
  −9%, but the whole edition fell more, so relative interest +12%".
- **Language ≠ country.** Polish Wikipedia readers include the diaspora; many
  Ukrainians also read Russian or English Wikipedia; English Wikipedia is global.
- **Views/month** compares audience size across languages; bigger editions naturally
  have more views. Share (views per million) compares intensity of interest.

## Confidence → wording

| Confidence | Say | Avoid |
|---|---|---|
| HIGH | "stable/clear growth", "consistent across months" | "proven demand" |
| MEDIUM | "signs of growth, but …(reason)" | presenting it as certain |
| LOW | "the data cannot support a trend claim because …(reason)" | hiding the finding or guessing |

Always name the main reason from `WHY` (low traffic, spike-driven, new article…).

## Missing articles and proxies

- No article in a language is itself a result: a **content gap** (less competition
  for learning content, but also no measurable demand on Wikipedia).
- Never fill the gap with invented numbers or with another language's numbers.
- A proxy (broader concept listed in `CHECK BEFORE ANSWERING`) measures a different,
  wider topic — e.g. "fasting" includes religious fasting and peaks around Lent and
  Ramadan. Offer it; use it only if the user agrees; label it in the answer and PDF.

## Recommendations for product decisions

Turn verdicts into a next step, not a final decision:

- growing + HIGH/MEDIUM + large audience → "prioritise for validation: landing page or
  ad test in <language>, survey of existing users who speak it";
- growing + small audience → "promising niche; validate cheaply before building";
- stable + large audience → "steady demand; differentiation matters more than timing";
- declining → "do not prioritise on this signal; check whether interest moved to
  related topics (rerun with a wider basket)";
- LOW confidence → "insufficient evidence; widen the basket or the period, or use
  another source (search trends, app-store keywords)".

## Answer skeleton (adapt, keep it short)

> **Answer:** <direction per language with share change and views/month>.
> **How sure:** <confidence> — <main reason>.
> **What it means for you:** <recommendation>.
> **Caveats:** <1-2 limitations>. Data: Wikipedia human pageviews <window>.

Example (uk):
> Інтерес до астрономії в україномовній Вікіпедії **спадає**: частка переглядів
> −46% за останні 12 місяців порівняно з попередніми (≈559 переглядів/міс).
> Довіра середня — через невеликий трафік; сильна шкільна сезонність (піки у
> вересні) свідчить, що аудиторія переважно учні. Для курсу це слабкий сигнал:
> варто перевірити попит опитуванням чи тестовою рекламою. Перегляди — це
> цікавість, а не готовність платити.

## When the user changes assumptions

Rerun with new flags and run `wiki.py diff <old> <new>`; report what changed and
whether the conclusion survived ("the ranking stayed pl > cs; uk moved from 2nd to
3rd once growth got more weight").
