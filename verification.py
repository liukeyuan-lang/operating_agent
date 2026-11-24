"""Evidence-backed verification for every activity; no inferred eligibility."""
import copy
import math
import hashlib
import json
from workflow import GATES,REQUIRED,classify,instant,profile_digest,project

TEAM_KEYS=('name','country','city','nationality','applicant_type','minimum_age','budget_cny','can_travel','notes')

def team_input(payload,previous):
    team=copy.deepcopy(previous)
    team.pop('weekly_hours',None)
    values=payload.get('team_profile',{})
    if not isinstance(values,dict):raise ValueError('团队信息需为对象')
    for key in TEAM_KEYS:
        if 'team_'+key not in payload and key not in values:continue
        value=payload.get('team_'+key,values.get(key))
        if value is None or value=='':team[key]=None;continue
        if key in {'minimum_age','budget_cny'}:
            value=float(value)
            if not math.isfinite(value) or value<0:raise ValueError('年龄和预算需为非负数字')
            if key=='minimum_age' and (value>120 or not value.is_integer()):raise ValueError('年龄需为0至120的整数')
        elif not isinstance(value,str) or len(value)>2000:raise ValueError('团队信息过长或格式不正确')
        else:value=value.strip()
        if key=='applicant_type' and value not in {'individual','team','company','student'}:raise ValueError('未知报名主体')
        if key=='can_travel' and value not in {'none','domestic','international'}:raise ValueError('未知出行能力')
        team[key]=value
    return team

def assess(item,profile,stamp):
    """Reevaluate supplied official rules against current project, on every update."""
    facts=item.get('facts',{});team=profile.get('team_profile',{});assets=profile.get('asset_references',[])
    gates={g:{'status':'unknown','reason':'缺少已核实的官方条件或项目资料'} for g in GATES}
    for gate in GATES:
        # Each deterministic comparison requires an explicitly complete rule set.
        key={'eligibility':'eligibility','asset_fit':'formats','rights_clearance':'rights','resource_fit':'attendance'}[gate]
        fact=facts.get(key,{})
        rule=fact.get('requirements',{})
        if fact.get('status')!='confirmed' or not rule.get('complete'):continue
        doc=next((d for d in item.get('official_sources',[]) if d['id']==fact.get('source_id')),None)
        if not doc or fact.get('evidence','') not in doc.get('excerpt','') or not fact.get('evidence'):continue
        from datetime import timedelta
        if instant(stamp)-instant(doc['read_at'])>timedelta(days=7):continue
        if gate=='eligibility':
            allowed={'countries','applicant_types','minimum_age','nationalities','complete'}
            if set(rule)-allowed:continue
            pairs=[('countries','country'),('applicant_types','applicant_type'),('nationalities','nationality')]
            checks=[]
            for rk,tk in pairs:
                if rk in rule:
                    choices=rule[rk]
                    checks.append(True if choices==['*'] else None if not team.get(tk) else team[tk] in choices)
            if 'minimum_age' in rule:checks.append(None if team.get('minimum_age') is None else team['minimum_age']>=rule['minimum_age'])
            if checks:gates[gate]=verdict(checks,'官方资格与已填写的团队信息逐项比对')
        elif gate=='asset_fit':
            if set(rule)-{'complete','min_width','min_height','min_duration','max_duration','media_type'}:continue
            checks=[]
            for asset in assets:
                if asset.get('availability')!='local':continue
                specs=asset.get('specs',{});tests=[]
                for rk,sk,op in [('min_width','width','min'),('min_height','height','min'),('min_duration','duration_seconds','min'),('max_duration','duration_seconds','max')]:
                    if rk in rule:tests.append(None if specs.get(sk) is None else specs[sk]>=rule[rk] if op=='min' else specs[sk]<=rule[rk])
                if 'media_type' in rule:tests.append(asset.get('locator','').lower().endswith('.'+rule['media_type'].lower()))
                if tests:checks.append(verdict(tests,'规格比对'))
            if any(c['status']=='pass' for c in checks):gates[gate]={'status':'pass','reason':'至少一份已登记本地素材符合完整官方技术规格；内容适配仍须Agent核对'}
            elif checks and all(c['status']=='fail' for c in checks):gates[gate]={'status':'fail','reason':'所有已登记本地素材均不符合官方必要技术规格'}
            # Technical pass alone cannot establish the full asset gate.
            if gates[gate]['status']=='pass':gates[gate]={'status':'unknown','reason':gates[gate]['reason']}
        elif gate=='rights_clearance':
            if set(rule)=={'complete','requires_cleared'} and rule['requires_cleared']:
                if assets and all(a.get('rights')=='cleared' for a in assets):gates[gate]={'status':'unknown','reason':'素材权属已登记，仍需核对本次许可范围和排他冲突'}
        elif gate=='resource_fit':
            if set(rule)-{'complete','travel'}:continue
            travel=rule.get('travel')
            if travel in {'domestic','international'} and team.get('can_travel')=='none':gates[gate]={'status':'fail','reason':'官方要求线下到场，团队登记为无法到场'}
    fee=facts.get('fees',{});fee_rule=fee.get('requirements',{})
    fee_doc=next((d for d in item.get('official_sources',[]) if d['id']==fee.get('source_id')),None)
    if (fee.get('status')=='confirmed' and fee.get('evidence') and fee_doc and fee['evidence'] in fee_doc.get('excerpt','')
        and 0<=(instant(stamp)-instant(fee_doc['read_at'])).total_seconds()<7*86400
        and isinstance(fee_rule.get('minimum_cost_cny'),(int,float)) and fee_rule['minimum_cost_cny']>=0
        and team.get('budget_cny') is not None and fee_rule['minimum_cost_cny']>team['budget_cny']):
        gates['resource_fit']={'status':'fail','reason':'官方已知必要费用超过团队单次机会总预算（均为人民币），未推断其他成本为零'}
    previous=item.get('participation',{})
    basis=hashlib.sha256(json.dumps({'facts':facts,'docs':item.get('official_sources',[])},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    reusable=previous.get('profile_digest')==profile_digest(profile) and previous.get('evidence_digest',basis)==basis
    if reusable and previous.get('checked_at') and 0<=(instant(stamp)-instant(previous['checked_at'])).total_seconds()<7*86400:
        # Retain the Agent's broader checks, but a deterministic failure wins.
        for g in GATES:
            if gates[g]['status']!='fail' and previous.get(g,{}).get('status') in {'pass','fail'}:gates[g]=previous[g]
    checked=previous.get('checked_at') if reusable and any(previous.get(g,{}).get('status') in {'pass','fail'} for g in GATES) else stamp
    return {'profile_digest':profile_digest(profile),'evidence_digest':basis,'checked_at':checked or stamp,**gates}

def verdict(checks,reason):
    return {'status':'fail' if False in checks else 'unknown' if None in checks else 'pass','reason':reason}

def refresh_checks(data,stamp,pid=None):
    profiles={p['id']:p for p in data['projects']}
    for item in data['items']:
        if pid and item['project_id']!=pid:continue
        p=profiles[item['project_id']]
        item['participation']=assess(item,p,stamp)
        bucket,issues=classify(item,p,at=stamp)
        attempt=item.get('verification_attempt',{})
        item['verification']={'status':'verified' if bucket=='result' else 'closed_or_ineligible' if bucket in {'history','excluded'} else 'blocked' if attempt.get('blocked') else 'needs_evidence',
             'checked_at':stamp,'issues':issues,'last_attempt_at':attempt.get('at'),'attempt_note':attempt.get('note'),
             'missing_team_fields':[k for k in ('country','applicant_type','budget_cny','can_travel') if p.get('team_profile',{}).get(k) is None]}

def tasks(data,pid=None):
    p=project(data,pid)
    from access_links import url_map,resolve_url,access_status
    visits=url_map(data,p['id'])
    from leads import library
    deleted={ref['id'] for row in library(data,p['id'],deleted=True) for ref in row['origins'] if ref['collection']=='items'}
    result=[]
    for i in data['items']:
        if i['project_id']!=p['id'] or i['id'] in deleted:continue
        bucket,issues=classify(i,p)
        if bucket in {'history','excluded','result'}:continue
        visit=resolve_url(i['url'],visits)
        result.append({'id':i['id'],'title':i['title'],'url':i['url'],'access_url':visit,'access_status':access_status(visit),'official_urls':[resolve_url(d['url'],visits) for d in i.get('official_sources',[])],
                       'issues':issues,'verification':i.get('verification'),'next_action':i.get('next_action'),
                       'profile_digest':profile_digest(p)})
    return result
