"""Offline fake of the Wikimedia/Wikidata endpoints used by the skill.

Serves real captured responses from tests/fixtures (see fixtures/README.md).
Daily pageviews are derived from real monthly totals (spread evenly across
days) except April 2025 for cs "Přerušovaný půst", which uses the real daily
series with the 2025-04-14 spike.
"""

from __future__ import annotations

import calendar
import json
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _monthly(name: str) -> dict[str, int]:
    return {it["timestamp"][:6]: it["views"] for it in load(name)["items"]}


ARTICLES = {
    ("cs.wikipedia", "Přerušovaný_půst"): _monthly("real_pv_cs_prerusovany_pust_monthly_2023-09_2026-08.json"),
    ("uk.wikipedia", "Астрономія"): _monthly("real_pv_uk_astronomiia_monthly_2023-09_2026-08.json"),
}
REAL_DAILY = {
    ("cs.wikipedia", "Přerušovaný_půst"): {
        it["timestamp"][:8]: it["views"] for it in load("real_pv_cs_prerusovany_pust_daily_2025-04.json")["items"]
    }
}
TOTALS = {
    "cs.wikipedia": _monthly("real_agg_cs_monthly_2023-09_2026-08.json"),
    "uk.wikipedia": _monthly("real_agg_uk_monthly_2023-09_2026-08.json"),
    "pl.wikipedia": _monthly("real_agg_pl_monthly_2023-09_2026-08.json"),
}


def daily_for(project: str, article: str, start: str, end: str) -> dict[str, int] | None:
    monthly = ARTICLES.get((project, article))
    if monthly is None:
        return None
    real = REAL_DAILY.get((project, article), {})
    out: dict[str, int] = {}
    d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    de = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    while d <= de:
        key = d.strftime("%Y%m%d")
        ym = key[:6]
        if key in real:
            out[key] = real[key]
        elif ym in monthly:
            n = calendar.monthrange(d.year, d.month)[1]
            base, rem = divmod(monthly[ym], n)
            out[key] = base + (1 if d.day <= rem else 0)
        d += timedelta(days=1)
    return out


class FakeWikimedia:
    """Callable transport: (url, headers, timeout) -> (status, headers, body)."""

    def __init__(self, extra_articles: dict | None = None, extra_totals: dict | None = None):
        self.calls: list[str] = []
        self.articles = dict(ARTICLES)
        self.totals = dict(TOTALS)
        if extra_articles:
            self.articles.update(extra_articles)
        if extra_totals:
            self.totals.update(extra_totals)
        self.user_agents: list[str] = []

    def _json(self, obj, status: int = 200):
        return status, {"content-type": "application/json"}, json.dumps(obj).encode("utf-8")

    def __call__(self, url: str, headers: dict, timeout: float):
        self.calls.append(url)
        self.user_agents.append(headers.get("User-Agent", ""))
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        if parts.netloc == "wikimedia.org":
            return self._pageviews(parts.path)
        if parts.netloc == "www.wikidata.org":
            return self._wikidata(q)
        if parts.netloc.endswith(".wikipedia.org"):
            return self._wikipedia(parts.netloc.split(".")[0], q)
        return self._json({"error": "unknown host"}, 404)

    # --- pageviews
    def _pageviews(self, path: str):
        not_found = load("real_pv_404_pl_post_przerywany.json")
        m = re.match(r"^/api/rest_v1/metrics/pageviews/per-article/([^/]+)/([^/]+)/([^/]+)/([^/]+)/daily/(\d{8})/(\d{8})$", path)
        if m:
            project, access, agent, art, s, e = m.groups()
            art = urllib.parse.unquote(art)
            monthly = self.articles.get((project, art))
            if monthly is None:
                return self._json(not_found, 404)
            if (project, art) in ARTICLES:
                values = daily_for(project, art, s, e)
            else:  # synthetic extra series given as {YYYYMMDD: views}
                values = {d: v for d, v in monthly.items() if s <= d <= e}
            items = [
                {"project": project, "article": art, "granularity": "daily", "timestamp": d + "00",
                 "access": access, "agent": agent, "views": v}
                for d, v in sorted(values.items()) if v > 0  # the API omits zero days
            ]
            if not items:
                return self._json(not_found, 404)
            return self._json({"items": items})
        m = re.match(r"^/api/rest_v1/metrics/pageviews/aggregate/([^/]+)/([^/]+)/([^/]+)/monthly/(\d{8})/(\d{8})$", path)
        if m:
            project, access, agent, s, e = m.groups()
            tot = self.totals.get(project)
            if tot is None:
                return self._json(not_found, 404)
            items = [
                {"project": project, "access": access, "agent": agent, "granularity": "monthly",
                 "timestamp": ym + "0100", "views": v}
                for ym, v in sorted(tot.items()) if s[:6] <= ym <= e[:6]
            ]
            return self._json({"items": items})
        return self._json(not_found, 404)

    # --- wikidata
    def _wikidata(self, q: dict):
        action = q.get("action")
        if action == "wbsearchentities":
            key = (q.get("search", "").casefold(), q.get("language"))
            table = {
                ("mercury", "en"): "real_wd_search_mercury_en.json",
                ("intermittent fasting", "en"): "real_wd_search_intermittent_fasting_en.json",
                ("астрономія", "uk"): "real_wd_search_astronomiia_uk.json",
            }
            name = table.get(key)
            if name:
                return self._json(load(name))
            return self._json({"searchinfo": {"search": q.get("search")}, "search": [], "success": 1})
        if action == "query" and q.get("prop") == "pageprops":
            src = {p["title"]: p for p in load("real_wd_pageprops_sitelinks.json")["query"]["pages"]}
            pages = []
            for t in q.get("titles", "").split("|"):
                pages.append(src.get(t, {"ns": 0, "title": t, "pageprops": {"wb-sitelinks": "0"}}))
            return self._json({"batchcomplete": True, "query": {"pages": pages}})
        if action == "wbgetclaims":
            claims = {
                ("Q1666254", "P279"): "Q44602",  # real: intermittent fasting -> subclass of fasting
                ("Q1666254", "P31"): "Q474191",  # real: instance of diet
            }
            target = claims.get((q.get("entity"), q.get("property")))
            if not target:
                return self._json({"claims": {}})
            snak = {"snaktype": "value", "property": q["property"],
                    "datavalue": {"value": {"entity-type": "item", "id": target}, "type": "wikibase-entityid"}}
            return self._json({"claims": {q["property"]: [{"mainsnak": snak, "type": "statement", "rank": "normal"}]}})
        if action == "wbgetentities":
            ents = load("real_wd_entities_Q1666254_Q333.json")["entities"]
            ents.update(load("real_wd_entities_Q44602_Q474191.json")["entities"])
            ents["Q308"] = {"type": "item", "id": "Q308", "labels": {"en": {"language": "en", "value": "Mercury"}},
                            "descriptions": {"en": {"language": "en", "value": "first planet from the Sun"}},
                            "sitelinks": {"cswiki": {"site": "cswiki", "title": "Merkur (planeta)"},
                                          "ukwiki": {"site": "ukwiki", "title": "Меркурій"}}}
            wanted_sites = set(q.get("sitefilter", "").split("|"))
            out = {}
            for qid in q.get("ids", "").split("|"):
                e = ents.get(qid)
                if not e:
                    out[qid] = {"id": qid, "missing": ""}
                    continue
                e = json.loads(json.dumps(e))
                e["sitelinks"] = {k: v for k, v in e.get("sitelinks", {}).items() if k in wanted_sites}
                out[qid] = e
            return self._json({"entities": out, "success": 1})
        return self._json({"error": {"code": "unknown"}}, 400)

    # --- wikipedia action api
    def _wikipedia(self, lang: str, q: dict):
        if q.get("prop") == "redirects":
            if lang == "cs":
                data = load("real_cswiki_redirects.json")
                titles = set(q.get("titles", "").split("|"))
                data["query"]["pages"] = [p for p in data["query"]["pages"] if p["title"] in titles]
                return self._json(data)
            return self._json({"batchcomplete": True, "query": {"pages": [{"title": t} for t in q.get("titles", "").split("|")]}})
        return self._json({"batchcomplete": True, "query": {"pages": []}})
