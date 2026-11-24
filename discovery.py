"""Opportunity-first exploration, global material packs and evidence-based ranking."""
import copy
import hashlib
import json
import re
from workflow import instant,project

DEFAULT_REQUIREMENTS='1. 非排他性的共创计划\n2. 正在开放的'
DEFAULT_SEEDS=['tripo 创作','即梦 创作','可灵 创作','AI创作者计划','AI创作大赛']
DIMENSIONS={'traffic':('流量扶持',30),'cash':('现金激励',25),'commercial':('商业合作',20),'exposure':('曝光增长',15),'assets':('素材匹配',10)}


def seeds(value):
    rows=value.splitlines() if isinstance(value,str) else value
    if not isinstance(rows,list) or len(rows)>50:raise ValueError('种子搜索词需为数组或逐行文本，最多50条')
    if any(not isinstance(v,str) or len(v)>200 for v in rows):raise ValueError('每条种子词最多200字')
    return list(dict.fromkeys(v.strip() for v in rows if v.strip()))


def requirement_lines(p):
    return [re.sub(r'^\s*\d+[.、）)]\s*','',s).strip() for s in p.get('exploration_requirements',DEFAULT_REQUIREMENTS).splitlines() if s.strip()]


def requirement_digest(p):
    return hashlib.sha256(json.dumps(requirement_lines(p),ensure_ascii=False).encode()).hexdigest()


def migrate_discovery(data):
    data.setdefault('material_packs',[])
    for p in data['projects']:
        if p.get('workspace','exploration')!='exploration' or p.get('discovery_version')==2:continue
        direction=p.get('direction','')
        if direction.startswith('请在界面填写'):direction=''
        p['exploration_requirements']=p.get('exploration_requirements') or direction or DEFAULT_REQUIREMENTS
        p['seed_keywords']=seeds(p.get('seed_keywords',DEFAULT_SEEDS))
        if p.get('materials'):
            old=copy.deepcopy(p['materials']);p['legacy_material_binding']=old
            if not any(r.get('fingerprint')==old['fingerprint'] for r in data['material_packs']):
                data['material_packs'].append({**old,'id':hashlib.sha256(old['fingerprint'].encode()).hexdigest()[:12],'name':p['name']+'的素材',
                    'assets':copy.deepcopy(p.get('asset_references',[])),'deleted':False,'origin':'legacy_project'})
        elif p.get('asset_references'):
            fingerprint='legacy:'+p['id']
            if not any(r.get('fingerprint')==fingerprint for r in data['material_packs']):
                data['material_packs'].append({'id':hashlib.sha256(fingerprint.encode()).hexdigest()[:12],'name':p['name']+'的素材','fingerprint':fingerprint,
                    'assets':copy.deepcopy(p['asset_references']),'deleted':False,'origin':'legacy_project'})
        p.pop('materials',None)
        if p.get('asset_references'):p['legacy_asset_references']=copy.deepcopy(p['asset_references'])
        p['asset_references']=[];p['assets_brief']='';p['discovery_version']=2
    for run in data.get('runs',[]):
        if run.get('status')=='running' and run.get('scenario')=='weekly_planning':
            run['legacy_scenario']='weekly_planning';run['scenario']='opportunity_discovery'
            run.get('targets',{}).pop('focus_areas',None)
    return data


def evidence_valid(item,proof,at):
    if not isinstance(proof,dict) or not isinstance(proof.get('quote'),str) or not proof['quote'].strip():return False
    doc=next((s for s in item.get('official_sources',[]) if s['id']==proof.get('source_id')),None)
    if not doc or proof['quote'] not in doc.get('excerpt',''):return False
    try:return 0<=(instant(at)-instant(doc['read_at'])).total_seconds()<=7*86400
    except (ValueError,KeyError):return False


def save_assessment(files,payload,at):
    def action(data):
        item=next((i for i in data['items'] if i['id']==payload.get('id')),None)
        if not item:raise ValueError('机会不存在')
        p=project(data,item['project_id']);rows=payload.get('requirements',[])
        expected=requirement_lines(p)
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows) or [r.get('requirement') for r in rows]!=expected:raise ValueError('需按当前探索要求逐项评估，顺序与原文必须一致')
        for r in rows:
            if r.get('status') not in {'pass','fail','unknown'} or not r.get('reason'):raise ValueError('要求评估需有状态和理由')
            if r['status']!='unknown' and not evidence_valid(item,r.get('evidence'),at):raise ValueError('已确认的要求判断必须引用新鲜官方原文')
        benefits=payload.get('benefits',{})
        if not isinstance(benefits,dict) or set(benefits)!=(set(DIMENSIONS)-{'assets'}):raise ValueError('需提供traffic/cash/commercial/exposure四项评估，未知填null')
        for key,row in benefits.items():
            if not isinstance(row,dict):raise ValueError('每项评分需要分数、理由和证据')
            score=row.get('score')
            if score is not None and (type(score) is not int or not 0<=score<=5):raise ValueError('各项分数须为0至5的整数，未知填null')
            if not row.get('reason'):raise ValueError('每项评分需要理由')
            if score is not None and not evidence_valid(item,row.get('evidence'),at):raise ValueError('权益评分必须引用新鲜官方原文，不得猜测奖励或获奖概率')
        matches=payload.get('asset_matches',[])
        if not isinstance(matches,list):raise ValueError('素材匹配需为数组')
        for m in matches:
            if not isinstance(m,dict):raise ValueError('素材匹配需含素材包ID、理解版本、分数及理由')
            pack=next((r for r in data.get('material_packs',[]) if r['id']==m.get('pack_id') and not r.get('deleted')),None)
            if not pack or m.get('analysis_id')!=pack.get('analysis_id'):raise ValueError('匹配的素材包不存在或理解版本已变化')
            if type(m.get('score')) is not int or not 0<=m['score']<=5 or not m.get('reason'):raise ValueError('素材匹配需有0至5分及具体依据')
        item['assessment']={'requirements':copy.deepcopy(rows),'requirements_digest':requirement_digest(p),
            'benefits':copy.deepcopy(benefits),'asset_matches':copy.deepcopy(matches),'assessed_at':at}
        item['updated_at']=at
        return item['assessment']
    return files.change(action)


def rank_candidate(item,p,packs,at):
    a=item.get('assessment',{});issues=[];status='pending'
    if item.get('excluded_reason') or item.get('historical'):status='excluded';issues.append(item.get('excluded_reason') or '历史机会')
    facts=item.get('facts',{})
    if facts.get('open_status',{}).get('value')=='closed':status='excluded';issues.append('已关闭')
    try:
        if facts.get('deadline',{}).get('at') and instant(facts['deadline']['at'])<=instant(at):status='excluded';issues.append('已截止')
    except ValueError:issues.append('截止时间格式无效')
    current=a.get('requirements_digest')==requirement_digest(p)
    rows=a.get('requirements',[]) if current else []
    valid=[]
    for r in rows:
        state=r['status'] if evidence_valid(item,r.get('evidence'),at) else 'unknown'
        valid.append(state)
        if state=='fail':status='excluded';issues.append(r['requirement']+'：'+r['reason'])
        elif state=='unknown':issues.append(r['requirement']+'：尚待确认')
    if not rows:issues.append('探索要求尚未完成当前版本的评估')
    if status!='excluded' and len(valid)==len(requirement_lines(p)) and all(s=='pass' for s in valid):status='matched'
    components=[];total=0;known=0
    for key,(label,weight) in DIMENSIONS.items():
        if key=='assets':continue
        row=a.get('benefits',{}).get(key,{}) if current else {}
        score=row.get('score') if evidence_valid(item,row.get('evidence'),at) else None
        points=round(score/5*weight,1) if score is not None else 0
        total+=points;known+=weight if score is not None else 0
        components.append({'key':key,'label':label,'weight':weight,'score':score,'points':points,'reason':row.get('reason','尚未评估或证据已过期'),'evidence':row.get('evidence')})
    active={r['id']:r for r in packs if not r.get('deleted')}
    matches=[m for m in a.get('asset_matches',[]) if m.get('pack_id') in active and m.get('analysis_id')==active[m['pack_id']].get('analysis_id')]
    best=max(matches,key=lambda m:m['score'],default=None) if current else None
    points=best['score']*2 if best else 0;total+=points
    components.append({'key':'assets','label':'素材匹配','weight':10,'score':best['score'] if best else None,'points':points,
                       'reason':best['reason'] if best else ('素材匹配待评估' if active else '素材库为空，不影响候选资格')})
    return {'total':round(total,1) if current else None,'known_weight':known+(10 if best else 0),'status':status,'issues':issues,
            'components':components,'best_material_pack':{'id':best['pack_id'],'name':active[best['pack_id']]['name']} if best else None,
            'assessed_at':a.get('assessed_at'),'requirements_current':current}
