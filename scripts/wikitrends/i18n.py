"""User-facing strings in English and Ukrainian.

Stdout for the agent is always English (models parse it best); the PDF uses
the language chosen with --ui (uk or en). Narrative text written by the agent
is used as-is.
"""

from __future__ import annotations

UI_LANGS = ("en", "uk")

DIRECTION = {
    "en": {"growing": "growing", "declining": "declining", "stable": "stable", "mixed": "mixed", "no_data": "no data"},
    "uk": {"growing": "зростає", "declining": "спадає", "stable": "стабільно", "mixed": "неоднозначно", "no_data": "немає даних"},
}

CONFIDENCE = {
    "en": {"HIGH": "high", "MEDIUM": "medium", "LOW": "low", "NONE": "—"},
    "uk": {"HIGH": "висока", "MEDIUM": "середня", "LOW": "низька", "NONE": "—"},
}

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uk": ["січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"],
}

FLAGS = {
    "no_article": {
        "en": "no article about {concepts} in this edition — interest cannot be measured here (content gap)",
        "uk": "у цьому мовному розділі немає статті про {concepts} — виміряти інтерес неможливо (прогалина в контенті)",
    },
    "no_views": {
        "en": "the article exists but has no recorded views in this period",
        "uk": "стаття існує, але за цей період переглядів не зафіксовано",
    },
    "partial_basket": {
        "en": "only {have} of {total} concepts have articles here; missing: {missing}",
        "uk": "статті є лише для {have} з {total} понять; бракує: {missing}",
    },
    "volume_critical": {
        "en": "very low traffic (~{avg} views/month) — too noisy for trend conclusions",
        "uk": "дуже малий трафік (~{avg} переглядів/міс) — забагато шуму для висновків про тренд",
    },
    "volume_warn": {
        "en": "low traffic (~{avg} views/month) — treat changes with caution",
        "uk": "невеликий трафік (~{avg} переглядів/міс) — зміни варто трактувати обережно",
    },
    "too_short": {
        "en": "only {n} months of data — trend cannot be separated from seasonality (use 24+ months)",
        "uk": "лише {n} міс. даних — тренд не відокремити від сезонності (потрібно 24+ міс.)",
    },
    "short_window": {
        "en": "under 24 months: compared the last {k} months with the same months a year earlier",
        "uk": "менше 24 міс.: порівняно останні {k} міс. з тими самими місяцями роком раніше",
    },
    "spike_driven": {
        "en": "change is driven by short spikes ({spike_share}% of recent views came from spike days; without them the change is {clean})",
        "uk": "зміна тримається на коротких сплесках ({spike_share}% недавніх переглядів — дні-сплески; без них зміна {clean})",
    },
    "spikes_present": {
        "en": "short spikes exist (largest {day}: {views} views vs ~{typical} typical) but do not change the conclusion",
        "uk": "є короткі сплески (найбільший {day}: {views} переглядів проти ~{typical} звичних), але висновок вони не змінюють",
    },
    "late_start": {
        "en": "'{title}' only has views from {first} (created or renamed during the period) — its growth is artificial",
        "uk": "«{title}» має перегляди лише з {first} (створена або перейменована в цей період) — її «зростання» штучне",
    },
    "narrow": {
        "en": "only {k} of {m} articles move in the same direction — the conclusion rests on few articles",
        "uk": "лише {k} з {m} статей рухаються в одному напрямку — висновок тримається на небагатьох статтях",
    },
    "not_significant": {
        "en": "trend test not significant (p={p}) — the change may be noise",
        "uk": "тест тренду незначущий (p={p}) — зміна може бути шумом",
    },
    "mixed_signals": {
        "en": "signals disagree: yearly change {change} but {cons} of {k} months beat the year before",
        "uk": "сигнали розходяться: річна зміна {change}, але лише {cons} з {k} міс. кращі за рік тому",
    },
    "platform_effect": {
        "en": "raw views changed {views} while the share of this Wikipedia's traffic changed {share} — the whole edition moved",
        "uk": "сирі перегляди змінилися на {views}, а частка в трафіку цієї Вікіпедії — на {share}: змінився весь розділ",
    },
    "seasonality": {
        "en": "strong seasonality: peaks in {months} ({ratio}x the quietest month)",
        "uk": "сильна сезонність: піки в {months} (у {ratio} раза більше за найтихіший місяць)",
    },
    "not_like_for_like": {
        "en": "languages share no common concept — comparison is not like-for-like",
        "uk": "у мов немає спільних понять — порівняння не рівноцінне",
    },
}

GLOBAL_NOTES = {
    "known_issue_2025": {
        "en": "Wikimedia reclassified hidden bot traffic for Mar–Aug 2025; comparisons across that period are less precise",
        "uk": "Wikimedia перекласифікувала приховані боти за бер–сер 2025; порівняння через цей період менш точні",
    },
}

LIMITATIONS = {
    "en": [
        "Pageviews show curiosity on Wikipedia, not willingness to pay — use them to choose what to validate next.",
        "A language edition is not a country: its readers may live anywhere.",
        "Views are not unique people; bots are filtered (agent=user) but not perfectly.",
        "Wikipedia traffic is shrinking overall (AI answers, social video), so trends are judged by each topic's share of its edition's traffic.",
        "The topic is represented only by the listed articles; related articles are not counted.",
    ],
    "uk": [
        "Перегляди показують цікавість у Вікіпедії, а не готовність платити — це сигнал, що перевіряти далі.",
        "Мовний розділ ≠ країна: його читачі можуть жити будь-де.",
        "Перегляди ≠ унікальні люди; ботів відфільтровано (agent=user), але не ідеально.",
        "Трафік Вікіпедії загалом падає (AI-відповіді, відео), тому тренд оцінюємо за часткою теми в трафіку свого розділу.",
        "Тему представляють лише перелічені статті; суміжні статті не враховано.",
    ],
}

LABELS = {
    "en": {
        "report_title": "Interest research: {topic}",
        "subtitle": "Wikipedia pageviews · {langs} · {window}",
        "answer": "Answer",
        "key_numbers": "Key numbers",
        "language": "Language",
        "avg_views": "Views / month",
        "change_views": "Change, views",
        "change_share": "Change, share",
        "direction": "Direction",
        "confidence": "Confidence",
        "why": "Why this confidence",
        "recommendation": "Recommendation",
        "next_steps": "Next steps",
        "limitations": "Assumptions & limitations",
        "method": "Method",
        "method_text": "Human views (agent=user), all devices. Change = {comparison}. Share = views per million views of the same Wikipedia edition. Confidence combines volume, spikes, article age, breadth, consistency and a seasonal trend test.",
        "articles": "Articles",
        "generated": "Generated {date} · run {run_id} · data: Wikimedia Pageviews API (wikimedia.org/api/rest_v1)",
        "no_data": "no article",
        "chart_views": "Monthly views",
        "chart_share": "Views per million views of the edition",
        "chart_growth": "Change of share, {comparison}",
        "comparison_12": "last 12 months vs previous 12",
        "comparison_k": "last {k} months vs same months a year earlier",
        "comparison_half": "second half vs first half of the period",
        "rank": "Rank",
        "score": "Score",
        "ranking_title": "Which audiences to explore next",
        "spike": "spike",
        "data_issue": "bot reclassification",
    },
    "uk": {
        "report_title": "Дослідження інтересу: {topic}",
        "subtitle": "Перегляди Вікіпедії · {langs} · {window}",
        "answer": "Відповідь",
        "key_numbers": "Ключові цифри",
        "language": "Мова",
        "avg_views": "Перегляди/міс",
        "change_views": "Зміна перегл.",
        "change_share": "Зміна частки",
        "direction": "Напрям",
        "confidence": "Довіра",
        "why": "Чому такий рівень довіри",
        "recommendation": "Рекомендація",
        "next_steps": "Наступні кроки",
        "limitations": "Припущення й обмеження",
        "method": "Метод",
        "method_text": "Перегляди людей (agent=user), усі пристрої. Зміна = {comparison}. Частка = перегляди на мільйон переглядів того самого мовного розділу. Довіра враховує обсяг, сплески, вік статей, ширину кошика, стабільність і сезонний тест тренду.",
        "articles": "Статті",
        "generated": "Згенеровано {date} · запуск {run_id} · дані: Wikimedia Pageviews API (wikimedia.org/api/rest_v1)",
        "no_data": "немає статті",
        "chart_views": "Перегляди за місяць",
        "chart_share": "Перегляди на млн переглядів розділу",
        "chart_growth": "Зміна частки: {comparison}",
        "comparison_12": "останні 12 міс. проти попередніх 12",
        "comparison_k": "останні {k} міс. проти тих самих місяців роком раніше",
        "comparison_half": "друга половина періоду проти першої",
        "rank": "Місце",
        "score": "Бал",
        "ranking_title": "Які аудиторії дослідити наступними",
        "spike": "сплеск",
        "data_issue": "перекласифікація ботів",
    },
}


def _localize_params(params: dict, ui: str) -> dict:
    out = dict(params)
    if isinstance(out.get("months"), list):
        out["months"] = month_names([int(m) for m in out["months"]], ui)
    if isinstance(out.get("ratio"), (int, float)):
        out["ratio"] = f"{out['ratio']:.1f}".replace(".", "," if ui == "uk" else ".")
    return out


def flag_text(flag_id: str, params: dict, ui: str = "en") -> str:
    tpl = FLAGS.get(flag_id, {}).get(ui) or FLAGS.get(flag_id, {}).get("en") or flag_id
    try:
        return tpl.format(**_localize_params(params, ui))
    except (KeyError, IndexError):
        return tpl


def label(key: str, ui: str = "en", **kw) -> str:
    text = LABELS.get(ui, LABELS["en"]).get(key) or LABELS["en"].get(key, key)
    return text.format(**kw) if kw else text


def month_names(months: list[int], ui: str = "en") -> str:
    return ", ".join(MONTHS[ui if ui in MONTHS else "en"][m - 1] for m in months)
