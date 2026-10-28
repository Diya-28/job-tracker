#!/usr/bin/env python3
"""Daily job watcher (India + abroad): pulls public ATS job-board APIs (Greenhouse, Lever, Ashby),
keeps roles posted in the last N hours in India/remote, scores them against Diya's
resume keywords, and writes docs/index.html + docs/jobs.json."""
import json, re, sys, html, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
UA = {"User-Agent": "jobwatch-personal/1.0 (personal job search)"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def parse_iso(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None

def from_greenhouse(slug):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in d.get("jobs", []):
        posted = parse_iso(j.get("first_published") or j.get("updated_at"))
        yield dict(company=slug, title=j.get("title", ""), location=(j.get("location") or {}).get("name", ""),
                   url=j.get("absolute_url", ""), posted=posted, text=html.unescape(re.sub("<[^>]+>", " ", j.get("content", ""))), src="greenhouse")

def from_lever(slug):
    d = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for j in d:
        ms = j.get("createdAt")
        posted = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None
        yield dict(company=slug, title=j.get("text", ""), location=(j.get("categories") or {}).get("location", "") or "",
                   url=j.get("hostedUrl", ""), posted=posted, text=j.get("descriptionPlain", ""), src="lever")

def from_ashby(slug):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for j in d.get("jobs", []):
        loc = j.get("location", "") or ""
        if j.get("isRemote"): loc += " Remote"
        yield dict(company=slug, title=j.get("title", ""), location=loc, url=j.get("jobUrl", ""),
                   posted=parse_iso(j.get("publishedAt")), text=j.get("descriptionPlain", ""), src="ashby")


FIRST_RUN, SEEN, NEWSEEN = True, set(), set()
CC = {"in": "India", "gb": "United Kingdom", "de": "Germany", "nl": "Netherlands", "ie": "Ireland", "ca": "Canada", "sg": "Singapore", "ae": "United Arab Emirates", "au": "Australia", "us": "United States", "fr": "France", "es": "Spain", "se": "Sweden", "ch": "Switzerland", "pt": "Portugal", "dk": "Denmark", "fi": "Finland", "pl": "Poland"}
AC = {"IND": "India", "USA": "United States", "GBR": "United Kingdom", "DEU": "Germany", "NLD": "Netherlands", "IRL": "Ireland", "CAN": "Canada", "SGP": "Singapore", "ARE": "United Arab Emirates", "AUS": "Australia"}

def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**UA, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def strip(h): return html.unescape(re.sub("<[^>]+>", " ", h or ""))

def wd_posted(txt, now):
    t = (txt or "").lower()
    if "today" in t: return now - timedelta(hours=2)
    if "yesterday" in t: return now - timedelta(hours=24)
    m = re.search(r"(\d+)\+?\s*days?", t)
    return now - timedelta(days=int(m.group(1))) if m else None

def from_workday(spec):
    """Workday career sites (NVIDIA, Salesforce, Adobe, Walmart...). Dates are 'Posted Today/Yesterday/N days ago'."""
    host, tenant, site = spec
    now, seen, base = datetime.now(timezone.utc), set(), f"https://{host}/wday/cxs/{tenant}/{site}"
    for term in CFG["search_terms"]:
        for off in (0, 20, 40):
            posts = post(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": off, "searchText": term}).get("jobPostings") or []
            if not posts: break
            for p in posts:
                path = p.get("externalPath", "")
                if not path or path in seen: continue
                seen.add(path)
                j = dict(company=tenant, title=p.get("title", ""), location=p.get("locationsText", ""), url=f"https://{host}/en-US/{site}{path}",
                         posted=wd_posted(p.get("postedOn"), now), text="", src="workday")
                info = None
                if re.match(r"\d+ locations?", j["location"].lower()):
                    try:
                        info = get(base + path).get("jobPostingInfo", {})
                        j["location"] = " ".join([info.get("location") or ""] + list(info.get("additionalLocations") or []))
                    except Exception: pass
                if not keep(j, now): continue
                try:
                    info = info or get(base + path).get("jobPostingInfo", {})
                    j["text"] = strip(info.get("jobDescription"))
                except Exception: pass
                yield j
            time.sleep(0.2)

def from_smartrecruiters(slug):
    now, seen = datetime.now(timezone.utc), set()
    for term in CFG["search_terms"]:
        for p in get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&q={urllib.parse.quote(term)}").get("content", []):
            pid = p.get("id")
            if not pid or pid in seen: continue
            seen.add(pid); loc = p.get("location") or {}
            L = ", ".join(x for x in [loc.get("city"), CC.get((loc.get("country") or "").lower(), loc.get("country"))] if x) + (" Remote" if loc.get("remote") else "")
            j = dict(company=slug, title=p.get("name", ""), location=L, url=f"https://jobs.smartrecruiters.com/{slug}/{pid}", posted=parse_iso(p.get("releasedDate")), text="", src="smartrecruiters")
            if not keep(j, now): continue
            try:
                ad = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}").get("jobAd", {}).get("sections", {})
                j["text"] = " ".join(strip((ad.get(k) or {}).get("text")) for k in ("jobDescription", "qualifications", "additionalInformation"))
            except Exception: pass
            yield j
        time.sleep(0.2)

def from_amazon(loc):
    """amazon.jobs search feed, newest first. Dates have day precision only."""
    now, seen = datetime.now(timezone.utc), set()
    for term in CFG["amazon_queries"]:
        d = get("https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode({"base_query": term, "loc_query": loc, "sort": "recent", "result_limit": 50, "offset": 0}))
        for p in d.get("jobs", []):
            jid = p.get("id_icims") or p.get("id")
            if jid in seen: continue
            seen.add(jid)
            try: dt = datetime.strptime(p.get("posted_date", ""), "%B %d, %Y").replace(hour=12, tzinfo=timezone.utc)
            except ValueError: dt = None
            if dt and dt > now: dt = now
            L = ", ".join(x for x in [p.get("city"), p.get("state"), AC.get(p.get("country_code"), p.get("country_code"))] if x)
            yield dict(company="amazon", title=p.get("title", ""), location=L, url="https://www.amazon.jobs" + p.get("job_path", ""), posted=dt,
                       text=strip(" ".join([p.get("description") or "", p.get("basic_qualifications") or "", p.get("preferred_qualifications") or ""])), src="amazon")
        time.sleep(0.3)

def from_atlassian(_slug):
    """Atlassian's listings feed has no reliable posting date, so only roles first seen after the first run are shown as new."""
    d = get("https://www.atlassian.com/endpoint/careers/listings")
    now = datetime.now(timezone.utc)
    for p in (d if isinstance(d, list) else d.get("jobs", [])):
        url = f"https://www.atlassian.com/company/careers/details/{p.get('id')}"
        NEWSEEN.add(url)
        if FIRST_RUN or url in SEEN: continue
        locs = p.get("locations") or [p.get("location", "")]
        yield dict(company="atlassian", title=p.get("title", ""), location=", ".join(map(str, locs)), url=url, posted=now, text="", src="atlassian")

SOURCES = {"greenhouse": from_greenhouse, "lever": from_lever, "ashby": from_ashby, "workday": from_workday, "smartrecruiters": from_smartrecruiters, "amazon": from_amazon, "atlassian": from_atlassian}

def regions_of(loc):
    l = loc.lower()
    return [r for r, terms in CFG["regions"].items() if any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", l) for t in terms)]

NEG_VISA = re.compile(r"\b(?:no|not|n't|cannot|unable|without|never)\W+(?:\w+\W+){0,6}?(?:visa|sponsor\w*)|\b(?:visa|sponsor\w*)\W+(?:\w+\W+){0,6}?(?:not|unavailable|n't)\b", re.I)

def visa_flag(text):
    t = text.lower()
    if any(k in t for k in CFG["visa_no"]) or NEG_VISA.search(t): return "no"
    if any(k in t for k in CFG["visa_yes"]): return "yes"
    return "?"

def keep(j, now):
    t = j["title"].lower()
    if not j["posted"]: return False
    j["regions"] = regions_of(j["location"])
    if not j["regions"]: return False
    limit = CFG["max_age_hours"] if j["regions"] == ["India"] else CFG["abroad_max_age_hours"]
    if now - j["posted"] > timedelta(hours=limit): return False
    if not any(k in t for k in CFG["title_must_match"]): return False
    if any(k in t for k in CFG["title_exclude"]): return False
    j["visa"] = visa_flag(j["text"])
    return True

# term -> (weight, on_resume, regex). Match = share of the JD's recognised skills that Diya's resume shows.
def _t(w, have, *alts): return (w, have, re.compile(r"(?<![a-z0-9+#])(?:" + "|".join(alts) + r")(?![a-z0-9+#])", re.I))
SKILLS = {
 "Python": _t(2,1,"python"), "SQL": _t(2,1,"sql","bigquery","postgres(?:ql)?"), "LLMs": _t(4,1,"llms?","large language models?","generative ai","genai","gen ai"),
 "RAG": _t(4,1,"rag","retrieval[- ]augmented"), "LangChain/LlamaIndex": _t(3,1,"langchain","llamaindex","llama[- ]index"), "Prompt engineering": _t(2,1,"prompt engineering","prompting"),
 "Fine-tuning": _t(3,1,"fine[- ]?tun\\w*","lora","peft"), "Agents": _t(3,1,"agentic","agents?","multi[- ]agent"), "Vector DBs": _t(2,1,"vector (?:db|database|store)s?","pinecone","faiss","chroma(?:db)?","weaviate","milvus"),
 "NLP": _t(2,1,"nlp","natural language"), "Forecasting/time series": _t(3,1,"forecast\\w*","time[- ]series","sarima","prophet","arima"), "Recommenders": _t(3,1,"recommend\\w+","personali[sz]ation","ranking"),
 "PyTorch": _t(3,1,"pytorch"), "TensorFlow": _t(2,1,"tensorflow","keras"), "scikit-learn/XGBoost": _t(2,1,"scikit-learn","sklearn","xgboost","lightgbm"), "Hugging Face": _t(2,1,"hugging ?face","transformers"),
 "Deep learning": _t(2,1,"deep learning","neural networks?"), "MLOps": _t(3,1,"mlops","ml pipelines?","model deployment","model serving","mlflow","kubeflow"), "Evaluation/A-B tests": _t(2,1,"a/b test\\w*","experimentation","model evaluation","evals?"),
 "Spark": _t(2,1,"spark","pyspark"), "Airflow/dbt": _t(2,1,"airflow","dbt"), "Snowflake": _t(1,1,"snowflake"), "GCP": _t(3,1,"gcp","google cloud","vertex ai","dataflow"), "AWS": _t(3,1,"aws","sagemaker","amazon web services"),
 "Docker/Kubernetes": _t(2,1,"docker","kubernetes","k8s"), "CI/CD": _t(1,1,"ci/cd","cicd"), "Looker/BI": _t(1,1,"looker","tableau","power ?bi"), "Anomaly detection": _t(1,1,"anomaly detection"), "REST APIs": _t(1,1,"rest(?:ful)? apis?","fastapi","flask"),
 "Java": _t(3,0,"java"), "Scala": _t(2,0,"scala"), "C++": _t(3,0,"c\\+\\+"), "Go": _t(2,0,"golang"), "Rust": _t(2,0,"rust"), "Azure": _t(3,0,"azure"), "Databricks": _t(2,0,"databricks"),
 "Kafka/Flink": _t(2,0,"kafka","flink","streaming"), "Terraform": _t(1,0,"terraform"), "Ray/vLLM/Triton": _t(2,0,"ray","vllm","triton","tensorrt"), "CUDA/GPU": _t(2,0,"cuda","gpus?","distributed training"),
 "Computer vision": _t(3,0,"computer vision","image recognition","object detection"), "Speech/audio": _t(2,0,"speech","asr","tts"), "Reinforcement learning/RLHF": _t(2,0,"reinforcement learning","rlhf"),
 "Search/IR": _t(2,0,"information retrieval","search relevance","learning to rank","elasticsearch"), "Causal inference": _t(2,0,"causal inference","bayesian"), "Knowledge graphs": _t(1,0,"knowledge graphs?","graph neural"),
}
CORE_TITLE = re.compile(r"\b(ai|ml|machine learning|genai|gen ai|llm|data scientist|applied scientist|nlp|mlops)\b", re.I)

def score(j):
    blob = j["title"] + " \n " + j["text"]
    hit = {k: v for k, v in SKILLS.items() if v[2].search(blob)}
    tot = sum(v[0] for v in hit.values())
    have = sum(v[0] for v in hit.values() if v[1])
    j["matched"] = sorted(k for k, v in hit.items() if v[1]); j["gaps"] = sorted(k for k, v in hit.items() if not v[1])
    yrs = [int(m) for m in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?years?", j["text"].lower()) if int(m) <= 20]
    j["yrs"] = max(yrs) if yrs else None
    if tot < 6: j["thin"] = True; base = 40 + (10 if CORE_TITLE.search(j["title"]) else 0)
    else: j["thin"] = False; base = 50 + (100 * have / tot - 50) * min(1, tot / 14) + (5 if CORE_TITLE.search(j["title"]) else 0)  # few recognised skills pull the score toward 50
    if j["yrs"] and j["yrs"] >= 7: base -= 15
    elif j["yrs"] and j["yrs"] >= 6: base -= 8
    return max(0, min(99, round(base)))

class Skip(Exception): pass

def from_arbeitnow(_slug):
    """arbeitnow.com free job board API (mostly Germany/EU, many relocation-friendly roles)."""
    now = datetime.now(timezone.utc)
    for page in (1, 2, 3):
        for p in get(f"https://www.arbeitnow.com/api/job-board-api?page={page}").get("data", []):
            ts = p.get("created_at")
            posted = datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float)) else None
            loc = (p.get("location") or "") + (" Remote" if p.get("remote") else "")
            text = strip(p.get("description")) + (" visa sponsorship" if p.get("visa_sponsorship") else "")
            m = re.search(r"arbeitnow\.([a-z.]+)/", p.get("url") or "")
            country = {"co.uk": "United Kingdom", "fr": "France", "nl": "Netherlands", "ch": "Switzerland"}.get(m.group(1) if m else "", "Germany")
            yield dict(company=p.get("company_name", ""), title=p.get("title", ""), location=f"{loc} {country}", url=p.get("url", ""), posted=posted, text=text, src="arbeitnow")
        time.sleep(0.3)

def from_adzuna(cc):
    """Adzuna aggregator API (free key): jobs gathered from many boards, with creation dates. Descriptions are short snippets."""
    import os
    app_id, app_key = os.environ.get("ADZUNA_ID"), os.environ.get("ADZUNA_KEY")
    if not app_id or not app_key: raise Skip("no ADZUNA_ID / ADZUNA_KEY secret")
    seen = set()
    for term in CFG["search_terms"]:
        q = urllib.parse.urlencode({"app_id": app_id, "app_key": app_key, "results_per_page": 50, "what": term, "max_days_old": 4, "sort_by": "date", "content-type": "application/json"})
        for p in get(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1?{q}").get("results", []):
            if p.get("id") in seen: continue
            seen.add(p.get("id")); loc = p.get("location") or {}
            L = ", ".join(list(loc.get("area") or []) or [loc.get("display_name", "")]) + ", " + CC.get(cc, cc)
            yield dict(company=(p.get("company") or {}).get("display_name", ""), title=p.get("title", ""), location=L, url=p.get("redirect_url", ""), posted=parse_iso(p.get("created")), text=strip(p.get("description")), src="adzuna")
        time.sleep(0.3)

SOURCES.update({"arbeitnow": from_arbeitnow, "adzuna": from_adzuna})

def remote_loc(geo):
    """Remote boards: 'worldwide / anywhere / APAC / Asia / India' roles can be done from India, so tag them as such."""
    g = (", ".join(map(str, geo)) if isinstance(geo, list) else str(geo or "")).strip()
    wide = (not g) or re.search(r"\b(worldwide|anywhere|global|apac|asia|india|any)\b", g, re.I)
    return f"{g or 'Worldwide'} Remote" + (" India" if wide else "")

def epoch(ts):
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
    return parse_iso(str(ts)) if ts else None

def from_jobicy(term):
    for p in get("https://jobicy.com/api/v2/remote-jobs?" + urllib.parse.urlencode({"count": 50, "tag": term})).get("jobs", []):
        yield dict(company=p.get("companyName", ""), title=p.get("jobTitle", ""), location=remote_loc(p.get("jobGeo")), url=p.get("url", ""),
                   posted=epoch(p.get("pubDate")), text=strip(p.get("jobDescription") or p.get("jobExcerpt")), src="jobicy")

def from_himalayas(term):
    d = get("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode({"q": term, "sort": "recent", "page": 1}))
    for p in d.get("jobs", []):
        yield dict(company=p.get("companyName", ""), title=p.get("title", ""), location=remote_loc(p.get("locationRestrictions") or []),
                   url=p.get("applicationLink") or p.get("guid") or "", posted=epoch(p.get("pubDate")),
                   text=strip(p.get("description") or p.get("excerpt")), src="himalayas")

def from_remoteok(_slug):
    d = get("https://remoteok.com/api")
    for p in (d if isinstance(d, list) else []):
        if not isinstance(p, dict) or not p.get("position"): continue
        yield dict(company=p.get("company", ""), title=p.get("position", ""), location=remote_loc(p.get("location")),
                   url=p.get("url") or ("https://remoteok.com/remote-jobs/" + str(p.get("slug", ""))), posted=epoch(p.get("epoch") or p.get("date")),
                   text=strip(p.get("description")) + " " + " ".join(p.get("tags") or []), src="remoteok")

def from_themuse(cat):
    for page in (1, 2, 3):
        for p in get("https://www.themuse.com/api/public/jobs?" + urllib.parse.urlencode({"page": page, "category": cat})).get("results", []):
            yield dict(company=(p.get("company") or {}).get("name", ""), title=p.get("name", ""), location=", ".join((l or {}).get("name", "") for l in p.get("locations") or []),
                       url=(p.get("refs") or {}).get("landing_page", ""), posted=epoch(p.get("publication_date")), text=strip(p.get("contents")), src="themuse")
        time.sleep(0.2)

SOURCES.update({"jobicy": from_jobicy, "himalayas": from_himalayas, "remoteok": from_remoteok, "themuse": from_themuse})

def li(title, loc="India"): return "https://www.linkedin.com/jobs/search/?keywords=" + urllib.parse.quote(title) + "&location=" + urllib.parse.quote(loc) + "&f_TPR=r86400&sortBy=DD"

def clean(j):
    """Real feeds contain nulls. Make every text field a string so nothing downstream can crash."""
    for k in ("company", "title", "location", "url", "text", "src"):
        j[k] = str(j.get(k) or "")
    return j

def run_one(kind, it, now):
    label = it[1] if isinstance(it, list) else it
    try:
        out = []
        for j in SOURCES[kind](it):
            j = clean(j)
            if j["url"] and keep(j, now):
                j["score"] = score(j); out.append(j)
        return label, kind, out, None
    except Skip as e:
        return label, kind, [], ("skip", str(e))
    except Exception as e:
        return label, kind, [], ("fail", repr(e)[:160])

def main():
    import hashlib, traceback
    from concurrent.futures import ThreadPoolExecutor
    now = datetime.now(timezone.utc)
    seen_p = ROOT / "seen.json"
    global FIRST_RUN, SEEN
    FIRST_RUN = not seen_p.exists()
    try: seen = SEEN = set(json.loads(seen_p.read_text())) if seen_p.exists() else set()
    except ValueError: seen = SEEN = set(); FIRST_RUN = True
    (ROOT / "docs").mkdir(exist_ok=True)
    tasks = [(kind, it) for kind, items in CFG.items() if kind in SOURCES for it in items]
    jobs, failed, skipped = [], [], []
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for label, kind, out, err in ex.map(lambda t: run_one(t[0], t[1], now), tasks):
                jobs += out
                if err and err[0] == "skip": skipped.append(f"{label} ({kind}): {err[1]}")
                elif err: failed.append(f"{label} ({kind})"); print("FAILED", label, kind, err[1])
        jobs = list({j["url"]: j for j in jobs}.values())
        for j in jobs: j["new"] = j["url"] not in seen
        jobs.sort(key=lambda j: (-j["new"], -j["score"]))
        out = [dict(id=hashlib.md5(j["url"].encode()).hexdigest()[:12], company=j["company"], title=j["title"], location=j["location"], regions=j["regions"],
                    visa=j["visa"], url=j["url"], posted=j["posted"].isoformat(), src=j["src"], score=j["score"], matched=j["matched"], gaps=j["gaps"],
                    yrs=j["yrs"], thin=j["thin"], new=j["new"], jd=re.sub(r"\s+", " ", j["text"]).strip()[:6000]) for j in jobs]
        (ROOT / "docs" / "jobs.json").write_text(json.dumps(dict(generated=now.isoformat(), jobs=out), ensure_ascii=False), encoding="utf-8")
        seen_p.write_text(json.dumps(sorted(seen | NEWSEEN | {j["url"] for j in jobs})))
        (ROOT / "docs" / "status.json").write_text(json.dumps(dict(generated=now.isoformat(), failed=failed, skipped=skipped, counts={k: sum(1 for j in jobs if j["src"] == k) for k in sorted({j["src"] for j in jobs})})))
        print(f"{len(jobs)} matches, {sum(j['new'] for j in jobs)} new, {len(failed)} boards failed")
    except Exception as e:
        traceback.print_exc()
        (ROOT / "docs" / "status.json").write_text(json.dumps(dict(generated=now.isoformat(), error=repr(e)[:300], failed=failed, skipped=skipped, counts={})))
        raise

if __name__ == "__main__":
    main()
