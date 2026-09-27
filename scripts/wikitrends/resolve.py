"""Topic -> Wikidata concept -> article title in every requested language.

Why Wikidata: a concept (QID) is the same meaning in every language, which is
what makes cross-language comparison fair. Search results are re-ranked by
the number of Wikipedia editions that have an article about the concept
("sitelinks"), because Wikidata's own order is not popularity: searching
"Mercury" returns a car brand before the planet.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import config, languages
from .cache import Cache
from .net import HttpClient

QID_RE = re.compile(r"^[Qq]\d+$")

NOISE_PATTERNS = (
    "wikimedia disambiguation page",
    "wikimedia list article",
    "wikimedia category",
    "wikimedia template",
    "wikimedia project page",
    "wikimedia internal item",
    "scholarly article",
    "scientific article",
    "clinical trial",
    "article published",
    "wikidata property",
    "властивість вікіданих",
    "сторінка значень",
    "family name",
    "given name",
    "surname",
)


@dataclass
class Candidate:
    qid: str
    label: str
    description: str
    sitelinks: int = 0
    exact: bool = False
    noise: bool = False


@dataclass
class Concept:
    query: str
    qid: str
    label: str
    description: str
    sitelinks: int
    titles: dict = field(default_factory=dict)  # lang -> title or None
    labels: dict = field(default_factory=dict)  # lang -> label
    ambiguous: bool = False
    weak_match: bool = False
    alternatives: list = field(default_factory=list)  # list[Candidate]
    source: str = "search"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["alternatives"] = [asdict(a) if isinstance(a, Candidate) else a for a in self.alternatives]
        return d


class ResolveError(Exception):
    pass


def _script_langs(text: str) -> list[str]:
    if re.search(r"[Ѐ-ӿ]", text):
        return ["uk", "ru", "be", "bg", "sr"]
    if re.search(r"[Ͱ-Ͽ]", text):
        return ["el"]
    if re.search(r"[؀-ۿ]", text):
        return ["ar", "fa"]
    if re.search(r"[぀-ヿ]", text):
        return ["ja"]
    if re.search(r"[一-鿿]", text):
        return ["zh", "ja"]
    if re.search(r"[가-힯]", text):
        return ["ko"]
    return ["en"]


def _is_noise(description: str) -> bool:
    d = (description or "").lower()
    return any(p in d for p in NOISE_PATTERNS)


def search_candidates(client: HttpClient, cache: Cache, query: str, lang: str, limit: int = 10) -> list[dict]:
    key = f"wd:search:{lang}:{query.casefold()}"
    cached = cache.kv_get(key)
    if cached is not None:
        return cached
    data = client.get_json(
        config.WIKIDATA_API,
        {
            "action": "wbsearchentities",
            "search": query,
            "language": lang,
            "uselang": lang,
            "type": "item",
            "limit": limit,
            "format": "json",
            "props": "",
        },
    )
    results = []
    for r in data.get("search", []):
        match = r.get("match") or {}
        results.append(
            {
                "id": r.get("id"),
                "label": r.get("label") or "",
                "description": r.get("description") or "",
                "match_type": match.get("type", ""),
                "match_text": match.get("text", ""),
                "aliases": r.get("aliases") or [],
            }
        )
    cache.kv_set(key, results)
    return results


def sitelink_counts(client: HttpClient, cache: Cache, qids: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    todo = []
    for q in qids:
        c = cache.kv_get(f"wd:sitelinks:{q}", ttl_days=30)
        if c is None:
            todo.append(q)
        else:
            out[q] = int(c)
    for i in range(0, len(todo), 50):
        chunk = todo[i : i + 50]
        data = client.get_json(
            config.WIKIDATA_API,
            {
                "action": "query",
                "prop": "pageprops",
                "ppprop": "wb-sitelinks",
                "titles": "|".join(chunk),
                "format": "json",
                "formatversion": "2",
            },
        )
        for page in data.get("query", {}).get("pages", []):
            q = page.get("title")
            n = int((page.get("pageprops") or {}).get("wb-sitelinks", 0))
            out[q] = n
            cache.kv_set(f"wd:sitelinks:{q}", n)
        for q in chunk:
            out.setdefault(q, 0)
    return out


def rank(query: str, raw: list[dict], counts: dict[str, int]) -> tuple[Candidate | None, list[Candidate], bool, bool]:
    """Return (best, alternatives, ambiguous, weak_match)."""
    qf = query.casefold().strip()
    cands: list[Candidate] = []
    seen = set()
    for r in raw:
        qid = r["id"]
        if not qid or qid in seen:
            continue
        seen.add(qid)
        exact = r["label"].casefold() == qf or (
            r.get("match_type") in ("label", "alias") and r.get("match_text", "").casefold() == qf
        ) or any(a.casefold() == qf for a in r.get("aliases", []))
        cands.append(
            Candidate(
                qid=qid,
                label=r["label"],
                description=r["description"],
                sitelinks=counts.get(qid, 0),
                exact=exact,
                noise=_is_noise(r["description"]),
            )
        )
    useful = [c for c in cands if not c.noise and c.sitelinks > 0]
    if not useful:
        useful = [c for c in cands if not c.noise] or cands
    if not useful:
        return None, [], False, False
    useful.sort(key=lambda c: (c.exact, c.sitelinks), reverse=True)
    best = useful[0]
    alternatives = [c for c in useful[1:4]]
    rivals = [
        c for c in useful[1:] if c.exact and c.sitelinks >= max(10, 0.35 * max(best.sitelinks, 1))
    ]
    ambiguous = bool(best.exact and rivals)
    weak = not best.exact
    return best, alternatives, ambiguous, weak


def fetch_entities(client: HttpClient, cache: Cache, qids: list[str], langs: list[str]) -> dict[str, dict]:
    """QID -> {"labels": {lang: label}, "descriptions": {...}, "titles": {lang: title}}"""
    label_langs = sorted(set(["en", "uk"] + langs))
    out: dict[str, dict] = {}
    todo = []
    for q in qids:
        c = cache.kv_get(f"wd:entity:{q}:{','.join(sorted(langs))}")
        if c is None:
            todo.append(q)
        else:
            out[q] = c
    for i in range(0, len(todo), 50):
        chunk = todo[i : i + 50]
        data = client.get_json(
            config.WIKIDATA_API,
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "sitelinks|labels|descriptions",
                "languages": "|".join(label_langs),
                "sitefilter": "|".join(languages.dbname(lang) for lang in langs),
                "format": "json",
                "formatversion": "2",
            },
        )
        entities = data.get("entities", {})
        for q in chunk:
            e = entities.get(q) or {}
            if e.get("missing") is not None or not e:
                raise ResolveError(f"Wikidata item {q} does not exist.")
            sitelinks = e.get("sitelinks") or {}
            titles = {}
            for lang in langs:
                sl = sitelinks.get(languages.dbname(lang))
                titles[lang] = sl.get("title") if sl else None
            item = {
                "labels": {k: v.get("value") for k, v in (e.get("labels") or {}).items()},
                "descriptions": {k: v.get("value") for k, v in (e.get("descriptions") or {}).items()},
                "titles": titles,
            }
            out[q] = item
            cache.kv_set(f"wd:entity:{q}:{','.join(sorted(langs))}", item)
    return out


def fetch_redirects(client: HttpClient, cache: Cache, lang: str, titles: list[str], limit_per_title: int = 20) -> dict[str, list[str]]:
    """Titles of redirect pages (namespace 0) pointing at each article."""
    out: dict[str, list[str]] = {}
    todo = []
    for t in titles:
        c = cache.kv_get(f"wp:redirects:{lang}:{t}")
        if c is None:
            todo.append(t)
        else:
            out[t] = c
    for i in range(0, len(todo), 50):
        chunk = todo[i : i + 50]
        found: dict[str, list[str]] = {t: [] for t in chunk}
        params = {
            "action": "query",
            "prop": "redirects",
            "rdnamespace": "0",
            "rdlimit": "max",
            "titles": "|".join(chunk),
            "format": "json",
            "formatversion": "2",
        }
        for _page in range(5):  # follow continuation a few times at most
            data = client.get_json(languages.api_url(lang), params)
            q = data.get("query", {})
            norm = {n["to"]: n["from"] for n in q.get("normalized", [])}
            for page in q.get("pages", []):
                title = norm.get(page.get("title"), page.get("title"))
                for r in page.get("redirects", []) or []:
                    found.setdefault(title, []).append(r["title"])
            cont = data.get("continue")
            if not cont:
                break
            params = {**params, **cont}
        for t, reds in found.items():
            reds = reds[:limit_per_title]
            out[t] = reds
            cache.kv_set(f"wp:redirects:{lang}:{t}", reds)
    return out


def split_topics(text: str) -> list[str]:
    sep = ";" if ";" in text else ","
    return [t.strip() for t in text.split(sep) if t.strip()]


RELATIONS = {"P279": "subclass of", "P361": "part of", "P31": "instance of"}


def broader_concepts(client: HttpClient, cache: Cache, qid: str, langs: list[str], limit: int = 6) -> list[dict]:
    """Broader/parent concepts (subclass of, part of, instance of) with articles in ALL langs.

    Used as clearly-labelled proxies when a concept has no article in some language.
    """
    key = f"wd:broader:{qid}:{','.join(sorted(langs))}"
    cached = cache.kv_get(key)
    if cached is not None:
        return cached
    targets: list[tuple[str, str]] = []
    for prop, relation in RELATIONS.items():
        data = client.get_json(
            config.WIKIDATA_API, {"action": "wbgetclaims", "entity": qid, "property": prop, "format": "json"}
        )
        for claim in (data.get("claims") or {}).get(prop, []):
            value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(value, dict) and value.get("id") and value["id"] not in [t for t, _ in targets]:
                targets.append((value["id"], relation))
    targets = targets[:limit]
    out: list[dict] = []
    if targets:
        ents = fetch_entities(client, cache, [t for t, _ in targets], langs)
        counts = sitelink_counts(client, cache, [t for t, _ in targets])
        for t, relation in targets:
            e = ents.get(t) or {}
            titles = e.get("titles", {})
            if titles and all(titles.get(lang) for lang in langs):
                out.append(
                    {
                        "qid": t,
                        "label": (e.get("labels") or {}).get("en") or t,
                        "relation": relation,
                        "titles": titles,
                        "sitelinks": counts.get(t, 0),
                    }
                )
    cache.kv_set(key, out)
    return out


def resolve_topics(
    client: HttpClient,
    cache: Cache,
    topics: list[str],
    langs: list[str],
    search_lang: str | None = None,
    qids: list[str] | None = None,
) -> tuple[list[Concept], list[str]]:
    """Resolve topics (names or QIDs) to concepts with per-language titles."""
    notes: list[str] = []
    picked: list[tuple[str, str, Candidate | None, list[Candidate], bool, bool, str]] = []
    items = [(t, None) for t in topics] + [(q, q) for q in (qids or [])]
    for text, forced in items:
        if forced or QID_RE.match(text):
            q = (forced or text).upper()
            picked.append((text, q, None, [], False, False, "qid"))
            continue
        order = [search_lang] if search_lang else _script_langs(text)
        for lang in langs + ["en"]:
            if lang not in order:
                order.append(lang)
        raw: list[dict] = []
        tried = []
        for lang in order[:4]:
            tried.append(lang)
            res = search_candidates(client, cache, text, lang)
            if any(not _is_noise(r["description"]) for r in res):
                raw = res
                break
            raw = raw or res
        if not raw:
            raise ResolveError(
                f"No Wikidata concept found for '{text}' (searched in: {', '.join(tried)}). "
                "Try the English name, a synonym, or pass --qids Q123 directly."
            )
        counts = sitelink_counts(client, cache, [r["id"] for r in raw if r.get("id")])
        best, alts, ambiguous, weak = rank(text, raw, counts)
        if best is None:
            raise ResolveError(f"No usable Wikidata concept for '{text}'. Pass --qids explicitly.")
        picked.append((text, best.qid, best, alts, ambiguous, weak, "search"))

    # de-duplicate concepts that resolved to the same QID
    uniq: dict[str, tuple] = {}
    for p in picked:
        if p[1] in uniq:
            notes.append(f"'{p[0]}' and '{uniq[p[1]][0]}' are the same concept ({p[1]}); counted once.")
            continue
        uniq[p[1]] = p

    entities = fetch_entities(client, cache, list(uniq), langs)
    counts_all = sitelink_counts(client, cache, list(uniq))
    concepts: list[Concept] = []
    for qid, (text, _q, best, alts, ambiguous, weak, source) in uniq.items():
        ent = entities[qid]
        labels = ent["labels"]
        label = labels.get("en") or (best.label if best else None) or next(iter(labels.values()), qid)
        concepts.append(
            Concept(
                query=text,
                qid=qid,
                label=label,
                description=(ent["descriptions"].get("en") or (best.description if best else "")),
                sitelinks=counts_all.get(qid, 0),
                titles=ent["titles"],
                labels=labels,
                ambiguous=ambiguous,
                weak_match=weak,
                alternatives=alts,
                source=source,
            )
        )
    return concepts, notes
