import re, html, requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app=FastAPI(title='Remote Job AI Agent',version='2.1')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
ROLES=['product owner','product manager','erp product owner','erp product manager','business systems analyst','systems analyst','erp consultant','digital transformation','analytics product owner']
SKILLS=['erp','infor ln','infor','baan','product roadmap','product backlog','backlog','user stories','acceptance criteria','agile','scrum','manufacturing','supply chain','sql','power bi','tableau','power apps','power automate','jira','confluence','data migration','data modelling','data cleansing','saas']
FX_TO_INR={'EUR':111.74,'USD':95.74,'GBP':130.57,'INR':1.0}
DEFAULT_MIN_INR=2400000

def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()
def split_queries(q): return [x.strip() for x in re.split(r'[,;\n]+',q or '') if x.strip()][:10]
def salary_to_inr(sal):
    if not sal or sal.get('max') is None: return None
    cur=str(sal.get('currency','')).upper().replace('$','USD').replace('€','EUR').replace('£','GBP')
    rate=FX_TO_INR.get(cur)
    if not rate: return None
    value=float(sal['max'])*rate
    period=str(sal.get('period','annual')).lower()
    if any(x in period for x in ['month','monthly']): value*=12
    elif any(x in period for x in ['week','weekly']): value*=52
    return round(value)
def score(j):
    t=' '.join([j.get('title',''),j.get('company',''),j.get('description',''),j.get('location','')]).lower(); roles=[x for x in ROLES if x in t]; skills=[x for x in SKILLS if x in t]
    return min(99,35+min(35,len(roles)*14)+min(20,len(skills)*3)+5),roles[:4],skills[:8]
def him(q):
    r=requests.get('https://himalayas.app/jobs/api/search',params={'q':q,'seniority':'Senior,Manager,Director','employment_type':'Full Time','sort':'relevant','page':1},timeout=20);r.raise_for_status();out=[]
    for j in r.json().get('jobs',[]):
        loc=', '.join(x.get('name','') if isinstance(x,dict) else str(x) for x in (j.get('locationRestrictions') or [])) or 'Worldwide';sal=None
        if j.get('minSalary') is not None or j.get('maxSalary') is not None: sal={'min':j.get('minSalary'),'max':j.get('maxSalary'),'currency':j.get('currency',''),'period':j.get('salaryPeriod','annual')}
        out.append({'id':'h:'+str(j.get('guid','')),'source':'Himalayas','title':j.get('title',''),'company':j.get('companyName',''),'location':loc,'geo':loc,'salary':sal,'description':clean(j.get('description') or j.get('excerpt','')),'url':j.get('applicationLink',''),'querySource':q})
    return out
def jobicy(q):
    r=requests.get('https://jobicy.com/api/v2/remote-jobs',params={'count':100},timeout=20);r.raise_for_status();out=[];terms=[x.lower() for x in q.split() if len(x)>2]
    for j in r.json().get('jobs',[]):
        t=' '.join(map(str,[j.get('jobTitle',''),j.get('jobExcerpt',''),j.get('jobDescription',''),j.get('jobIndustry',''),j.get('jobGeo','')])).lower()
        if terms and not all(x in t for x in terms): continue
        sal=None
        if j.get('salaryMin') is not None or j.get('salaryMax') is not None: sal={'min':j.get('salaryMin'),'max':j.get('salaryMax'),'currency':j.get('salaryCurrency',''),'period':j.get('salaryPeriod','yearly')}
        out.append({'id':'j:'+str(j.get('id','')),'source':'Jobicy','title':j.get('jobTitle',''),'company':j.get('companyName',''),'location':j.get('jobGeo','Anywhere'),'geo':j.get('jobGeo','Anywhere'),'salary':sal,'description':clean(j.get('jobDescription') or j.get('jobExcerpt','')),'url':j.get('url',''),'querySource':q})
    return out
@app.get('/api/health')
def health(): return {'ok':True,'version':'2.1','minimumSalaryINR':DEFAULT_MIN_INR,'fxToINR':FX_TO_INR}
@app.get('/api/jobs')
def jobs(q:str=Query('Product Owner ERP'),europe_only:bool=False,min_salary_inr:int=DEFAULT_MIN_INR,limit:int=50,include_salary_unknown:bool=False):
    queries=split_queries(q) or ['Product Owner ERP'];raw=[];errors=[]
    for query in queries:
        for fn,name in [(him,'Himalayas'),(jobicy,'Jobicy')]:
            try: raw+=fn(query)
            except Exception as e: errors.append(f'{name} ({query}): {e}')
    seen=set();out=[]
    for j in raw:
        k=re.sub(r'[^a-z0-9]','',(j['title']+'|'+j['company']).lower())
        if k in seen: continue
        seen.add(k);s,r,sk=score(j);salary_inr=salary_to_inr(j.get('salary'));eligible=salary_inr is not None and salary_inr>min_salary_inr
        if not eligible and not (include_salary_unknown and salary_inr is None): continue
        j.update(score=s,matchedRoles=r,matchedSkills=sk,salaryINR=salary_inr,salaryEligible=eligible);out.append(j)
    out.sort(key=lambda x:(x['score'],x['salaryINR'] or 0),reverse=True)
    return {'count':len(out[:limit]),'jobs':out[:limit],'errors':errors,'filters':{'queries':queries,'worldwideRemote':not europe_only,'minimumSalaryINR':min_salary_inr,'strictSalaryFilter':not include_salary_unknown},'sources':['Himalayas','Jobicy'],'fxToINR':FX_TO_INR}
app.mount('/',StaticFiles(directory='static',html=True),name='static')
