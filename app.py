import re, html, requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app=FastAPI(title='Remote Job AI Agent',version='2.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
EUROPE={'albania','andorra','austria','belarus','belgium','bosnia and herzegovina','bulgaria','croatia','cyprus','czechia','czech republic','denmark','estonia','finland','france','germany','greece','hungary','iceland','ireland','italy','kosovo','latvia','liechtenstein','lithuania','luxembourg','malta','moldova','monaco','montenegro','netherlands','north macedonia','norway','poland','portugal','romania','san marino','serbia','slovakia','slovenia','spain','sweden','switzerland','ukraine','united kingdom','uk','england','scotland','wales','northern ireland'}
ROLES=['product owner','product manager','erp product owner','erp product manager','business systems analyst','systems analyst','erp consultant','digital transformation','analytics product owner']
SKILLS=['erp','infor ln','infor','baan','product roadmap','product backlog','backlog','user stories','acceptance criteria','agile','scrum','manufacturing','supply chain','sql','power bi','tableau','power apps','power automate','jira','confluence','data migration','data modelling','data cleansing','saas']
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()
def euro_ok(j):
    t=' '.join([str(j.get('geo','')),str(j.get('location','')),str(j.get('locationRestrictions',''))]).lower()
    return any(x in t for x in ['worldwide','anywhere','europe','eu remote']) or any(c in t for c in EUROPE)
def score(j):
    t=' '.join([j.get('title',''),j.get('company',''),j.get('description',''),j.get('location','')]).lower(); roles=[x for x in ROLES if x in t]; skills=[x for x in SKILLS if x in t]
    s=min(99,35+min(35,len(roles)*14)+min(20,len(skills)*3)+(5 if euro_ok(j) else 0)); sal=j.get('salary'); eligible=bool(sal and sal.get('currency')=='EUR' and (sal.get('max') or 0)>=50000); return s,roles[:4],skills[:8],eligible
def him(q):
    r=requests.get('https://himalayas.app/jobs/api/search',params={'q':q,'seniority':'Senior,Manager,Director','employment_type':'Full Time','sort':'relevant','page':1},timeout=20);r.raise_for_status();out=[]
    for j in r.json().get('jobs',[]):
        loc=', '.join(x.get('name','') if isinstance(x,dict) else str(x) for x in (j.get('locationRestrictions') or [])) or 'Worldwide';sal=None
        if j.get('minSalary') is not None or j.get('maxSalary') is not None: sal={'min':j.get('minSalary'),'max':j.get('maxSalary'),'currency':j.get('currency',''),'period':j.get('salaryPeriod','annual')}
        out.append({'id':'h:'+str(j.get('guid','')),'source':'Himalayas','title':j.get('title',''),'company':j.get('companyName',''),'location':loc,'geo':loc,'salary':sal,'description':clean(j.get('description') or j.get('excerpt','')),'url':j.get('applicationLink','')})
    return out
def jobicy(q):
    r=requests.get('https://jobicy.com/api/v2/remote-jobs',params={'count':100},timeout=20);r.raise_for_status();out=[];terms=[x.lower() for x in q.split() if len(x)>2]
    for j in r.json().get('jobs',[]):
        t=' '.join(map(str,[j.get('jobTitle',''),j.get('jobExcerpt',''),j.get('jobDescription',''),j.get('jobIndustry',''),j.get('jobGeo','')])).lower()
        if terms and not all(x in t for x in terms): continue
        sal=None
        if j.get('salaryMin') is not None or j.get('salaryMax') is not None: sal={'min':j.get('salaryMin'),'max':j.get('salaryMax'),'currency':j.get('salaryCurrency',''),'period':j.get('salaryPeriod','yearly')}
        out.append({'id':'j:'+str(j.get('id','')),'source':'Jobicy','title':j.get('jobTitle',''),'company':j.get('companyName',''),'location':j.get('jobGeo','Anywhere'),'geo':j.get('jobGeo','Anywhere'),'salary':sal,'description':clean(j.get('jobDescription') or j.get('jobExcerpt','')),'url':j.get('url','')})
    return out
@app.get('/api/health')
def health(): return {'ok':True,'version':'2.0'}
@app.get('/api/jobs')
def jobs(q:str=Query('Product Owner ERP'),europe_only:bool=True,min_salary_eur:int=50000,limit:int=50):
    raw=[];errors=[]
    for fn,name in [(him,'Himalayas'),(jobicy,'Jobicy')]:
        try: raw+=fn(q)
        except Exception as e: errors.append(f'{name}: {e}')
    seen=set();out=[]
    for j in raw:
        k=re.sub(r'[^a-z0-9]','',(j['title']+'|'+j['company']).lower())
        if k in seen or (europe_only and not euro_ok(j)): continue
        seen.add(k);s,r,sk,eligible=score(j);j.update(score=s,matchedRoles=r,matchedSkills=sk,salaryEligible=eligible);out.append(j)
    out.sort(key=lambda x:(x['score'],x['salaryEligible']),reverse=True)
    return {'count':len(out[:limit]),'jobs':out[:limit],'errors':errors,'filters':{'query':q,'europeOnly':europe_only,'minimumSalaryEUR':min_salary_eur},'sources':['Himalayas','Jobicy']}
app.mount('/',StaticFiles(directory='static',html=True),name='static')
