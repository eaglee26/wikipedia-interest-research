"""Wikipedia language editions: code validation, friendly names, API endpoints.

Cheap models often write country codes instead of language codes (cz, ua, jp)
or pass language names ("Polish", "польська"). We normalise these with a note
instead of failing, and warn about codes that are valid but often mistaken
(se = Northern Sami, not Swedish). Codes we do not know are still allowed —
existence is verified against the Pageviews API later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# code: (English name, Ukrainian name)
LANGUAGES: dict[str, tuple[str, str]] = {
    "en": ("English", "англійська"),
    "de": ("German", "німецька"),
    "fr": ("French", "французька"),
    "es": ("Spanish", "іспанська"),
    "it": ("Italian", "італійська"),
    "pt": ("Portuguese", "португальська"),
    "ru": ("Russian", "російська"),
    "uk": ("Ukrainian", "українська"),
    "pl": ("Polish", "польська"),
    "cs": ("Czech", "чеська"),
    "sk": ("Slovak", "словацька"),
    "sl": ("Slovenian", "словенська"),
    "hr": ("Croatian", "хорватська"),
    "sr": ("Serbian", "сербська"),
    "bs": ("Bosnian", "боснійська"),
    "sh": ("Serbo-Croatian", "сербохорватська"),
    "bg": ("Bulgarian", "болгарська"),
    "mk": ("Macedonian", "македонська"),
    "ro": ("Romanian", "румунська"),
    "hu": ("Hungarian", "угорська"),
    "el": ("Greek", "грецька"),
    "tr": ("Turkish", "турецька"),
    "nl": ("Dutch", "нідерландська"),
    "sv": ("Swedish", "шведська"),
    "no": ("Norwegian (Bokmål)", "норвезька (букмол)"),
    "nn": ("Norwegian (Nynorsk)", "норвезька (нюношк)"),
    "da": ("Danish", "данська"),
    "fi": ("Finnish", "фінська"),
    "et": ("Estonian", "естонська"),
    "lv": ("Latvian", "латиська"),
    "lt": ("Lithuanian", "литовська"),
    "be": ("Belarusian", "білоруська"),
    "be-tarask": ("Belarusian (Taraškievica)", "білоруська (тарашкевиця)"),
    "ka": ("Georgian", "грузинська"),
    "hy": ("Armenian", "вірменська"),
    "az": ("Azerbaijani", "азербайджанська"),
    "kk": ("Kazakh", "казахська"),
    "uz": ("Uzbek", "узбецька"),
    "ky": ("Kyrgyz", "киргизька"),
    "tg": ("Tajik", "таджицька"),
    "ar": ("Arabic", "арабська"),
    "arz": ("Egyptian Arabic", "єгипетська арабська"),
    "he": ("Hebrew", "іврит"),
    "fa": ("Persian", "перська"),
    "ur": ("Urdu", "урду"),
    "hi": ("Hindi", "гінді"),
    "bn": ("Bengali", "бенгальська"),
    "ta": ("Tamil", "тамільська"),
    "te": ("Telugu", "телугу"),
    "mr": ("Marathi", "маратхі"),
    "ml": ("Malayalam", "малаялам"),
    "kn": ("Kannada", "каннада"),
    "gu": ("Gujarati", "гуджараті"),
    "pa": ("Punjabi", "панджабі"),
    "th": ("Thai", "тайська"),
    "vi": ("Vietnamese", "в'єтнамська"),
    "id": ("Indonesian", "індонезійська"),
    "ms": ("Malay", "малайська"),
    "tl": ("Tagalog", "тагальська"),
    "ja": ("Japanese", "японська"),
    "ko": ("Korean", "корейська"),
    "zh": ("Chinese", "китайська"),
    "zh-yue": ("Cantonese", "кантонська"),
    "ca": ("Catalan", "каталанська"),
    "eu": ("Basque", "баскська"),
    "gl": ("Galician", "галісійська"),
    "ga": ("Irish", "ірландська"),
    "cy": ("Welsh", "валлійська"),
    "is": ("Icelandic", "ісландська"),
    "sq": ("Albanian", "албанська"),
    "af": ("Afrikaans", "африкаанс"),
    "sw": ("Swahili", "суахілі"),
    "eo": ("Esperanto", "есперанто"),
    "la": ("Latin", "латина"),
    "simple": ("Simple English", "спрощена англійська"),
    "ceb": ("Cebuano", "себуанська"),
}

# Invalid codes models often produce (country codes, ISO 639-2/3) -> Wikipedia code
MISTAKES: dict[str, str] = {
    "cz": "cs", "ua": "uk", "gr": "el", "jp": "ja", "dk": "da", "ee": "et", "kr": "ko",
    "cn": "zh", "rs": "sr", "by": "be", "kz": "kk", "ge": "ka", "iw": "he", "in": "id",
    "ji": "yi", "jw": "jv", "mo": "ro", "sp": "es", "nb": "no",
    "eng": "en", "ukr": "uk", "pol": "pl", "cze": "cs", "ces": "cs", "deu": "de", "ger": "de",
    "fra": "fr", "fre": "fr", "rus": "ru", "spa": "es", "ita": "it", "por": "pt", "jpn": "ja",
    "zho": "zh", "chi": "zh", "kor": "ko", "tur": "tr", "vie": "vi", "ind": "id", "ara": "ar",
    "heb": "he", "hin": "hi", "swe": "sv", "nor": "no", "nob": "no", "dan": "da", "fin": "fi",
    "est": "et", "lav": "lv", "lit": "lt", "slk": "sk", "slo": "sk", "slv": "sl", "hrv": "hr",
    "srp": "sr", "bul": "bg", "ron": "ro", "rum": "ro", "hun": "hu", "ell": "el", "gre": "el",
    "nld": "nl", "dut": "nl", "cat": "ca", "tha": "th", "fas": "fa", "per": "fa", "ben": "bn",
    "msa": "ms", "may": "ms", "kaz": "kk", "bel": "be", "geo": "ka", "kat": "ka", "arm": "hy",
    "hye": "hy", "aze": "az", "uzb": "uz",
}

# Valid editions that are frequently used by mistake
EASILY_CONFUSED: dict[str, str] = {
    "se": "'se' is Northern Sami Wikipedia; Swedish is 'sv'",
    "si": "'si' is Sinhala Wikipedia; Slovenian is 'sl'",
    "sh": "'sh' is Serbo-Croatian Wikipedia; Serbian is 'sr', Croatian 'hr'",
    "ceb": "Cebuano Wikipedia is mostly bot-generated articles; traffic is atypical",
    "simple": "Simple English Wikipedia is for learners; English is 'en'",
}

# Special database names (sitelink ids) that do not follow "<code with _>wiki"
SPECIAL_DBNAMES = {"be-tarask": "be_x_oldwiki"}

_CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,10})*$")


def _name_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for code, (en, uk) in LANGUAGES.items():
        idx[en.lower()] = code
        idx[en.lower().split(" (")[0]] = idx.get(en.lower().split(" (")[0], code)
        idx[uk.lower()] = code
    # a few frequent adjective forms ("польськомовна", "україномовна", "англомовний")
    idx.update({"україномовна": "uk", "україномовний": "uk", "англомовна": "en", "англомовний": "en"})
    return idx


_NAMES = _name_index()


def _stem_lookup(word: str) -> str | None:
    """Match Ukrainian adjective forms: 'польською', 'польськомовній' -> pl."""
    w = word.lower().strip()
    for code, (_en, uk) in LANGUAGES.items():
        uk_l = uk.lower()
        if uk_l.endswith("ська") or uk_l.endswith("цька") or uk_l.endswith("зька"):
            stem = uk_l[:-1]  # "польськ"
            if len(stem) >= 5 and w.startswith(stem):
                return code
    if w.startswith("україном"):
        return "uk"
    if w.startswith("англом"):
        return "en"
    return None


@dataclass
class LangCheck:
    codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize_langs(raw: str | list[str]) -> LangCheck:
    items = raw if isinstance(raw, list) else re.split(r"[,;\s]+", raw)
    out = LangCheck()
    for item in items:
        token = item.strip()
        if not token:
            continue
        low = token.lower().replace("_", "-")
        if low.endswith(".wikipedia") or low.endswith(".wikipedia.org"):
            low = low.split(".wikipedia")[0]
        code: str | None = None
        if low in LANGUAGES:
            code = low
        elif low in MISTAKES:
            code = MISTAKES[low]
            out.notes.append(f"Language '{token}' is not a Wikipedia code; using '{code}' ({name(code)}).")
        elif low in _NAMES:
            code = _NAMES[low]
            out.notes.append(f"Language '{token}' -> '{code}'.")
        elif (stem := _stem_lookup(low)) is not None:
            code = stem
            out.notes.append(f"Language '{token}' -> '{code}'.")
        elif _CODE_RE.match(low):
            code = low  # unknown to our table; existence is checked via the API later
        else:
            out.errors.append(
                f"'{token}' is not a Wikipedia language code. Use codes like pl, cs, uk, en, de."
            )
            continue
        if code is None:  # pragma: no cover - every branch above sets it or continues
            continue
        if code in EASILY_CONFUSED:
            out.notes.append(EASILY_CONFUSED[code])
        if code not in out.codes:
            out.codes.append(code)
    if not out.codes and not out.errors:
        out.errors.append("No languages given. Pass --langs with Wikipedia codes, e.g. --langs pl,cs")
    return out


def name(code: str, ui: str = "en") -> str:
    if code in LANGUAGES:
        en, uk = LANGUAGES[code]
        return uk if ui == "uk" else en
    return code


def project(code: str) -> str:
    return f"{code}.wikipedia"


def dbname(code: str) -> str:
    return SPECIAL_DBNAMES.get(code, code.replace("-", "_") + "wiki")


def api_url(code: str) -> str:
    return f"https://{code}.wikipedia.org/w/api.php"


def article_url(code: str, title: str) -> str:
    from urllib.parse import quote

    return f"https://{code}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='')}"
