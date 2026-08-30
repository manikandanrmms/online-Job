import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Global Remote Job AI Agent", version="3.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ROLES = [
    "product owner","product manager","erp product owner","erp product manager",
    "business systems analyst","systems analyst","erp consultant",
    "digital transformation","analytics product owner","program manager",
    "project manager","business analyst"
]
SKILLS = [
    "erp","infor ln","infor","baan","product roadmap","product backlog","backlog",
    "user stories","acceptance criteria","agile","scrum","manufacturing","supply chain",
    "sql","power bi","tableau","power apps","power automate","jira","confluence",
    "data migration","data modelling","data cleansing","saas","digital transformation"
]

DEFAULT_MIN_USD = 50000
TTL = 3600
CACHE = {}
FX_CACHE = {"at": 0, "rates": {"USD": 1.0}, "date": None}

REGIONS = {
    "Worldwide/Anywhere": [],
    "North America": ["united states","usa","canada","mexico","north america"],
    "Europe": ["europe","emea","uk","united kingdom","germany","france","ireland","spain","italy","netherlands","sweden","switzerland","poland","portugal","denmark","norway","finland","belgium","austria"],
    "Asia-Pacific": ["asia","apac","india","singapore","australia","new zealand","japan","philippines","south korea","hong kong","thailand","vietnam","indonesia"],
    "Latin America": ["latam","latin america","brazil","argentina","chile","colombia","costa rica","peru","uruguay"],
    "Africa": ["africa","south africa","nigeria","kenya","egypt","morocco","ghana"],
    "Middle East": ["middle east","israel","uae","united arab emirates","saudi arabia","qatar","jordan","turkey","turkiye"]
}

SOURCES = [
    {"name":"Himalayas","type":"JSON API","enabled":True,"verified":"2026-08-30",
     "freeApply":"Free access; employer application may vary","url":"https://himalayas.app/api",
     "notes":"Public API; canonical application/listing link retained."},
    {"name":"Jobicy","type":"JSON API","enabled":True,"verified":"2026-08-30",
     "freeApply":"Free access; employer application may vary","url":"https://jobicy.com/api/v2/remote-jobs",
     "notes":"Public API; canonical listing link retained."},
    {"name":"We Work Remotely","type":"RSS","enabled":True,"verified":"2026-08-30",
     "freeApply":"Free access; employer application may vary","url":"https://weworkremotely.com/remote-job-rss-feed",
     "notes":"Public RSS feed; listings link back to source."},
    {"name":"Remote OK","type":"JSON feed","enabled":True,"verified":"2026-08-30",
     "freeApply":"Free access; employer application may vary","url":"https://remoteok.com/api",
     "notes":"Public JSON feed; attribution/source link retained."},
    {"name":"Arbeitnow","type":"Public API","enabled":True,"verified":"2026-08-30",
     "freeApply":"Free access; employer application may vary","url":"https://www.arbeitnow.com/api/job-board-api",
     "notes":"Public job-board API; source attribution retained."},
    {"name":"Working Nomads","type":"Website","enabled":False,"verified":"2026-08-30",
     "freeApply":"Free browsing; supported public aggregation feed not verified","url":"https://www.workingnomads.com/",
     "notes":"Available as external search until a permitted feed/API is confirmed."},
    {"name":"Remotive","type":"API/Website","enabled":False,"verified":"2026-08-30",
     "freeApply":"Free access; redistribution terms apply","url":"https://remotive.com/remote-jobs/api",
     "notes":"Not copied into this aggregator until redistribution permission is confirmed."},
    {"name":"Wellfound","type":"Website","enabled":False,"verified":"2026-08-30",
     "freeApply":"Free candidate access","url":"https://wellfound.com/candidates/remote",
     "notes":"Direct external search; no unsupported scraping."},
    {"name":"Remote.co","type":"Website","enabled":False,"verified":"2026-08-30",
     "freeApply":"Free browsing","url":"https://remote.co/remote-jobs/",
     "notes":"Direct external search; no supported public aggregation API verified."},
    {"name":"FlexJobs","type":"Website","enabled":False,"verified":"2026-08-30",
     "freeApply":"Paid membership for full access","url":"https://www.flexjobs.com/",
     "notes":"Direct external search only; excluded from free aggregated feeds."},
    {"name":"LinkedIn","type":"Website/API","enabled":False,"verified":"2026-08-30",
     "freeApply":"Free candidate access; API access requires authorization","url":"https://www.linkedin.com/jobs/",
     "notes":"Direct remote-job search; no unauthorized scraping."},
    {"name":"Naukri","type":"Website/API","enabled":False,"verified":"2026-08-30",
     "freeApply":"Free candidate access; API access varies","url":"https://www.naukri.com/",
     "notes":"Direct work-from-home search; no unauthorized scraping."},
    {"name":"Indeed / Glassdoor / Monster / CareerBuilder / SimplyHired","type":"Website/API",
     "enabled":False,"verified":"2026-08-30","freeApply":"Varies","url":"",
     "notes":"External search only unless an authorized feed/API is available."}
]

def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))).strip()

def parse_date(v: Any):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def split_queries(q):
    return [x.strip().lower() for x in re.split(r"[,;\n]+", q or "") if x.strip()][:12]

def matches(job, search_terms):
    if not search_terms:
        return True
    text = " ".join(str(job.get(k,"")) for k in ("title","company","description","location","tags")).lower()
    return any(t in text for t in search_terms)

def remote_info(job):
    loc = str(job.get("location") or "").strip()
    text = f"{loc} {job.get('description','')}".lower()
    tz = re.findall(r"(?:utc|gmt)\s*[+-]?\s*\d{1,2}(?::\d{2})?|[a-z]+\s+time\s+zones?", text, re.I)
    if any(x in text for x in ["worldwide","anywhere","global","work from anywhere","distributed globally"]):
        return "Worldwide", "Global", tz
    for region, words in REGIONS.items():
        if region != "Worldwide/Anywhere" and any(w in text for w in words):
            return "Region-locked", region, tz
    return "Remote", loc or "Remote", tz

def remote_policy(desc):
    t = str(desc or "").lower()
    if any(x in t for x in ["remote-first","remote first","fully distributed","100% remote","all-remote","entirely remote"]):
        return "Remote-First", "Inferred from listing"
    if any(x in t for x in ["remote-friendly","remote friendly","distributed company","distributed team","remote employees"]):
        return "Remote-Friendly", "Inferred from listing"
    if any(x in t for x in ["remote","work from home","hybrid"]):
        return "Remote-OK", "Inferred from listing"
    return "Unknown", "Not stated"

def compensation_notes(desc):
    t = str(desc or "").lower()
    mapping = [
        ("equity","Equity"),("stock options","Stock options"),("bonus","Bonus"),
        ("health insurance","Health insurance"),("medical insurance","Medical"),
        ("401k","401(k)"),("pension","Pension"),("paid time off","Paid time off"),("pto","PTO")
    ]
    return [label for key,label in mapping if key in t][:8]

def normalize(job, source):
    rt, scope, tz = remote_info(job)
    policy, evidence = remote_policy(job.get("description",""))
    job.update(source=source, remoteType=rt, remoteScope=scope,
               timezoneRestrictions=tz, companyRemotePolicy=policy,
               remotePolicyEvidence=evidence,
               compensationNotes=compensation_notes(job.get("description","")))
    return job

def score(job):
    text = " ".join(str(job.get(k,"")) for k in ("title","company","description","location","tags")).lower()
    roles = [x for x in ROLES if x in text]
    skills = [x for x in SKILLS if x in text]
    s = min(99, 35 + min(35,len(roles)*14) + min(20,len(skills)*3) + (8 if job.get("remoteType")=="Worldwide" else 0))
    return s, roles[:5], skills[:10]

def fx_rates():
    now = time.time()
    if now-FX_CACHE["at"] < TTL and len(FX_CACHE["rates"]) > 1:
        return FX_CACHE
    fallback = {"USD":1.0,"EUR":0.875,"GBP":0.746,"INR":96.34,"CAD":1.37,"AUD":1.53,"SGD":1.28,"JPY":163.0,"CHF":0.81}
    try:
        r = requests.get("https://api.frankfurter.dev/v2/rates", params={"base":"USD"}, timeout=10)
        r.raise_for_status()
        rows = r.json()
        rates = {"USD":1.0}
        for row in rows:
            if row.get("quote") and row.get("rate"):
                rates[row["quote"]] = float(row["rate"])
        FX_CACHE.update({"at":now,"rates":rates,"date":rows[0].get("date") if rows else None})
    except Exception:
        FX_CACHE.update({"at":now,"rates":fallback,"date":"fallback"})
    return FX_CACHE

def salary_usd(sal, rates):
    if not sal:
        return None, None
    cur = str(sal.get("currency") or "").upper().replace("$","USD").replace("€","EUR").replace("£","GBP")
    rate = rates.get(cur)
    if not rate:
        return None, None
    period = str(sal.get("period") or "annual").lower()
    factor = 12 if "month" in period else 52 if "week" in period else 1
    def cv(v):
        return round(float(v)/rate*factor,2) if v is not None else None
    return cv(sal.get("min")), cv(sal.get("max"))

def get_json(key, url, params=None):
    now = time.time()
    if key in CACHE and now-CACHE[key]["at"] < TTL:
        return CACHE[key]["data"]
    r = requests.get(url, params=params or {}, timeout=20, headers={"User-Agent":"GlobalRemoteJobAggregator/3.1"})
    r.raise_for_status()
    data = r.json()
    CACHE[key] = {"at":now,"data":data}
    return data

def himalayas(search_terms):
    out=[]
    for term in search_terms or [""]:
        data=get_json("him:"+term,"https://himalayas.app/jobs/api/search",
                      {"q":term,"seniority":"Senior,Manager,Director","employment_type":"Full Time","sort":"recent","page":1})
        for j in data.get("jobs",[]):
            loc=", ".join(x.get("name","") if isinstance(x,dict) else str(x) for x in (j.get("locationRestrictions") or [])) or "Worldwide"
            sal=None
            if j.get("minSalary") is not None or j.get("maxSalary") is not None:
                sal={"min":j.get("minSalary"),"max":j.get("maxSalary"),"currency":j.get("currency",""),"period":j.get("salaryPeriod","annual")}
            out.append(normalize({
                "id":"h:"+str(j.get("guid","")),"title":j.get("title",""),"company":j.get("companyName",""),
                "location":loc,"salary":sal,"description":clean(j.get("description") or j.get("excerpt","")),
                "url":j.get("applicationLink") or j.get("url",""),
                "posted":parse_date(j.get("publishedAt") or j.get("pubDate")),"tags":j.get("categories",[])
            },"Himalayas"))
    return out

def jobicy(search_terms):
    data=get_json("jobicy","https://jobicy.com/api/v2/remote-jobs",{"count":200})
    out=[]
    for j in data.get("jobs",[]):
        job=normalize({
            "id":"j:"+str(j.get("id","")),"title":j.get("jobTitle",""),"company":j.get("companyName",""),
            "location":j.get("jobGeo","Anywhere"),
            "salary":({"min":j.get("salaryMin"),"max":j.get("salaryMax"),"currency":j.get("salaryCurrency",""),"period":j.get("salaryPeriod","yearly")}
                     if j.get("salaryMin") is not None or j.get("salaryMax") is not None else None),
            "description":clean(j.get("jobDescription") or j.get("jobExcerpt","")),"url":j.get("url",""),
            "posted":parse_date(j.get("pubDate")),"tags":j.get("jobIndustry",[])
        },"Jobicy")
        if matches(job,search_terms): out.append(job)
    return out

def remote_ok(search_terms):
    data=get_json("remoteok","https://remoteok.com/api")
    out=[]
    for j in data if isinstance(data,list) else []:
        if not j.get("id") or "legal" in j: continue
        job=normalize({
            "id":"rok:"+str(j.get("id")),"title":j.get("position",""),"company":html.unescape(j.get("company","")),
            "location":clean(j.get("location","")) or "Worldwide",
            "salary":({"min":j.get("salary_min"),"max":j.get("salary_max"),"currency":"USD","period":"annual"}
                     if j.get("salary_min") or j.get("salary_max") else None),
            "description":clean(j.get("description","")),"url":j.get("apply_url") or j.get("url",""),
            "posted":parse_date(j.get("date")),"tags":j.get("tags",[])
        },"Remote OK")
        if matches(job,search_terms): out.append(job)
    return out

def we_work_remotely(search_terms):
    now=time.time()
    if "wwr" in CACHE and now-CACHE["wwr"]["at"] < TTL:
        root=ET.fromstring(CACHE["wwr"]["data"])
    else:
        r=requests.get("https://weworkremotely.com/remote-jobs.rss",timeout=20,
                       headers={"User-Agent":"GlobalRemoteJobAggregator/3.1"})
        r.raise_for_status()
        CACHE["wwr"]={"at":now,"data":r.text}
        root=ET.fromstring(r.text)
    out=[]
    for item in root.findall(".//item"):
        def val(tag):
            n=item.find(tag)
            return n.text if n is not None else ""
        job=normalize({
            "id":"wwr:"+val("guid"),"title":clean(val("title")),
            "company":clean(val("author")) or "We Work Remotely listing","location":"Worldwide",
            "salary":None,"description":clean(val("description")),"url":val("link"),
            "posted":parse_date(val("pubDate")),"tags":[clean(val("category"))]
        },"We Work Remotely")
        if matches(job,search_terms): out.append(job)
    return out

def arbeitnow(search_terms):
    data=get_json("arbeitnow","https://www.arbeitnow.com/api/job-board-api")
    rows=data.get("data",[]) if isinstance(data,dict) else []
    out=[]
    for j in rows:
        job=normalize({
            "id":"an:"+str(j.get("slug") or j.get("id") or j.get("url")),
            "title":j.get("title",""),"company":j.get("company_name",""),
            "location":j.get("location","Remote"),"salary":None,
            "description":clean(j.get("description","")),"url":j.get("url",""),
            "posted":parse_date(j.get("created_at") or j.get("createdAt")),
            "tags":j.get("tags",[])
        },"Arbeitnow")
        if matches(job,search_terms): out.append(job)
    return out

def dedupe(jobs):
    seen=set();out=[]
    for j in jobs:
        url=re.sub(r"^https?://(www\.)?","",str(j.get("url","")).lower()).rstrip("/")
        title=re.sub(r"[^a-z0-9]","",str(j.get("title","")).lower())
        company=re.sub(r"[^a-z0-9]","",str(j.get("company","")).lower())
        key=url or f"{title}|{company}"
        if key in seen: continue
        seen.add(key);out.append(j)
    return out

def enrich(jobs):
    rates=fx_rates()["rates"]
    for j in jobs:
        mn,mx=salary_usd(j.get("salary"),rates)
        s,roles,skills=score(j)
        j.update(score=s,matchedRoles=roles,matchedSkills=skills,
                 salaryMinUSD=mn,salaryMaxUSD=mx,
                 salaryUnknown=(mn is None and mx is None))
    return jobs

@app.get("/api/health")
def health():
    fx=fx_rates()
    return {"ok":True,"version":"3.1","defaultMinimumUSD":DEFAULT_MIN_USD,
            "fx":fx,"enabledSources":[s["name"] for s in SOURCES if s["enabled"]]}

@app.get("/api/sources")
def sources():
    return {"sources":SOURCES,"verifiedAt":"2026-08-30"}

@app.get("/api/fx")
def fx():
    return fx_rates()

@app.get("/api/jobs")
def jobs(
    q:str=Query("Product Owner, ERP Product Owner, Product Manager, Infor LN"),
    region:str=Query("Worldwide/Anywhere"), country:str=Query(""),
    min_salary_usd:float=Query(50000), max_salary_usd:float|None=Query(None),
    salary_mode:str=Query("paid"), remote_policy:str=Query("Any"),
    sort:str=Query("relevance"), page:int=Query(1,ge=1), per_page:int=Query(50,ge=1,le=100)
):
    search_terms=split_queries(q)
    raw=[];errors=[]
    for fn,name in [
        (himalayas,"Himalayas"),(jobicy,"Jobicy"),(remote_ok,"Remote OK"),
        (we_work_remotely,"We Work Remotely"),(arbeitnow,"Arbeitnow")
    ]:
        try: raw.extend(fn(search_terms))
        except Exception as e: errors.append(f"{name}: {type(e).__name__}")
    all_jobs=enrich(dedupe(raw))
    filtered=[]
    for j in all_jobs:
        blob=(str(j.get("remoteScope",""))+" "+str(j.get("location",""))+" "+str(j.get("description",""))).lower()
        if region!="Worldwide/Anywhere":
            allowed=REGIONS.get(region,[])
            if j["remoteType"]!="Worldwide" and not any(x in blob for x in allowed): continue
        if country and country.lower() not in blob: continue
        if remote_policy!="Any" and j.get("companyRemotePolicy")!=remote_policy: continue
        if salary_mode=="paid":
            if j["salaryMaxUSD"] is None or j["salaryMaxUSD"]<min_salary_usd: continue
            if max_salary_usd is not None and j["salaryMinUSD"] is not None and j["salaryMinUSD"]>max_salary_usd: continue
        elif salary_mode=="negotiable":
            if not j["salaryUnknown"]: continue
        elif salary_mode=="all":
            if j["salaryMaxUSD"] is not None and j["salaryMaxUSD"]<min_salary_usd: continue
        filtered.append(j)
    if sort=="date":
        filtered.sort(key=lambda x:x.get("posted") or "",reverse=True)
    elif sort=="salary_desc":
        filtered.sort(key=lambda x:x.get("salaryMaxUSD") or 0,reverse=True)
    elif sort=="salary_asc":
        filtered.sort(key=lambda x:x.get("salaryMinUSD") or 10**9)
    elif sort=="company":
        filtered.sort(key=lambda x:str(x.get("company","")).lower())
    else:
        filtered.sort(key=lambda x:(x.get("score",0),x.get("salaryMaxUSD") or 0),reverse=True)
    total=len(filtered);start=(page-1)*per_page
    page_jobs=filtered[start:start+per_page]
    return {"count":len(page_jobs),"total":total,"page":page,"perPage":per_page,
            "pages":(total+per_page-1)//per_page,"jobs":page_jobs,"errors":errors,
            "sources":[s["name"] for s in SOURCES if s["enabled"]],"fx":fx_rates()}
app.mount("/",StaticFiles(directory="static",html=True),name="static")
