"""Project-scoped discovery entries over existing files, with reversible removal."""
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit
from uuid import uuid4

from platforms import account_url,content_url,detect_platform,platform
from workflow import classify,project
from access_links import remember_links

KINDS={"creator":"创作者/团队","organization":"机构/主办方","topic":"话题/关键词",
       "website":"网站/社区","work":"作品/案例","opportunity":"活动/合作线索","other":"其他入口"}
FOLLOWUP_KINDS=set(KINDS)|{"official","peer","search"}
STATUSES={'new','explored','blocked','watching','observed','historical'}
SELECTION_POLICY='agent_decides'
NEXT={"creator":"查看近期作品、参加的活动和合作方，提取新的入口。",
      "organization":"查看官方动态、合作项目和往届活动，寻找当前开放入口。",
      "topic":"搜索相关讨论与创作者，沿新出现的作品、活动和机构继续查找。",
      "website":"浏览近期更新、栏目及外链，发现新的征集或创作社区。",
      "work":"查看作者、展出背景与合作机构，沿作品的发现路径继续探索。",
      "opportunity":"由Agent追溯原始来源和关联机构，判断是否值得投入。",
      "other":"搜索这个对象及关联来源，说明新发现对项目的价值。"}


def clean_target(value):
    if not isinstance(value,str) or not value.strip() or len(value)>4000:raise ValueError("请填写链接、名字或关键词")
    value=value.strip()
    if '://' not in value:
        if value.lower().startswith(('javascript:','data:','file:')):raise ValueError("链接仅支持HTTP(S)")
        return value
    parsed=urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:raise ValueError("链接需为不含账号密码的HTTP(S)地址")
    selected=detect_platform(value)
    if selected!='web':
        try:return content_url(value,selected)
        except ValueError:pass
        try:return account_url(value,selected)
        except ValueError:pass
    drop={'xsec_token','xsec_source','source','ref','s','fbclid','log_pb','enter_from','enter_method','channel_type','parent_page_channel_type'}
    query=[(k,v) for k,v in parse_qsl(parsed.query) if k not in drop and not k.startswith('utm_')]
    return urlunsplit((parsed.scheme.lower(),parsed.netloc.lower(),parsed.path.rstrip('/') or '/',urlencode(sorted(query)),''))


def identity(target,selected):
    value=clean_target(target)
    if '://' not in value:value=' '.join(value.casefold().split())
    return selected+'|'+value


def library(data,pid=None,deleted=False):
    profile=project(data,pid);pid=profile['id'];groups={}
    deleted_keys={row['key']:row for row in data.get('lead_deletions',[]) if row['project_id']==pid}
    for collection in ('followups','sources','signals','items'):
        for row in data.get(collection,[]):
            if row['project_id']!=pid:continue
            if collection=='items' and classify(row,profile)[0]=='result':continue
            target=(row.get('target') or row.get('title')) if collection=='signals' else row.get('target') or row.get('url') or row.get('title')
            if not target:continue
            try:target=clean_target(target)
            except ValueError:continue
            selected=detect_platform(target) if collection!='signals' and '://' in target else row.get('platform') or detect_platform(target)
            selected=platform(selected)['id'] if selected!='web' else 'web'
            key=identity(target,selected)
            if (key in deleted_keys)!=deleted:continue
            title=row.get('label') or row.get('title') or row.get('name') or target
            if collection=='followups':kind={'official':'organization','peer':'creator','search':'topic'}.get(row.get('kind'),row.get('kind','other'))
            elif collection=='sources':kind={'peer':'creator','organizer':'organization','information':'website'}.get(row.get('role'),'other')
            elif collection=='signals':kind='work' if row.get('kind')=='peer_pattern' else 'topic' if row.get('kind')=='topic' else 'other'
            else:kind='opportunity'
            if kind not in KINDS:kind='other'
            reason=row.get('reason') or row.get('fit_reason') or row.get('summary') or '保留为后续搜索入口。'
            status=row.get('status','new') if collection=='followups' else 'watching' if collection=='sources' else 'observed' if collection=='signals' else {'lead':'new','history':'historical','excluded':'historical'}[classify(row,profile)[0]]
            path=list(row.get('discovery_path',[]))
            if collection=='signals':
                for evidence in row.get('evidence',[]):
                    node={'label':evidence.get('title') or '原始观察','url':evidence.get('url'),'reason':evidence.get('excerpt','')}
                    if node not in path:path.append(node)
            if row.get('parent_url'):path.append({'label':'发现来源','url':row['parent_url'],'reason':reason})
            ref={'collection':collection,'id':row['id']}
            entry={'id':collection+':'+row['id'],'key':key,'project_id':pid,'kind':kind,'kind_label':KINDS[kind],
                   'title':title,'target':target,'url':target if target.startswith(('http://','https://')) else None,'platform':selected,
                   'reason':reason,'summary':row.get('summary') or row.get('latest_observation') or '',
                   'next_step':row.get('next_step') or row.get('next_action') or NEXT[kind],
                   'status':status,'origin':row.get('origin','agent'),'origins':[ref],'discovery_path':path,
                   'decision_note':row.get('decision_note',''),'decision_at':row.get('decision_at'),
                   'updated_at':row.get('updated_at') or row.get('last_seen_at') or row.get('added_at') or row.get('first_seen_at') or row.get('created_at') or '',
                   'deleted_at':deleted_keys.get(key,{}).get('at')}
            if key in groups:
                existing=groups[key];existing['origins'].append(ref)
                if status=='watching' and not existing['decision_at']:existing['status']='watching'
                for node in path:
                    if node not in existing['discovery_path']:existing['discovery_path'].append(node)
                if reason!=existing['reason'] and reason not in existing.setdefault('additional_reasons',[]):existing['additional_reasons'].append(reason)
            else:groups[key]=entry
    rows=sorted(groups.values(),key=lambda row:row['updated_at'],reverse=True)
    return sorted(rows,key=lambda row:row['origin']!='manual')


def _fields(payload):
    kind=payload.get('kind','other')
    if kind not in KINDS:raise ValueError("请选择线索类型")
    if not all(isinstance(payload.get(k,''),str) for k in ('title','reason','next_step')):raise ValueError("名称、搜索价值和下一步需为文字")
    title=payload.get('title','').strip();reason=payload.get('reason','').strip()
    if not title or len(title)>200 or not reason or len(reason)>2000:raise ValueError("请填写名称（200字内）和搜索价值（2000字内）")
    target=clean_target(payload.get('target') or title)
    inferred=detect_platform(target)
    selected=payload.get('platform') or inferred
    selected=platform(selected)['id'] if selected!='web' else 'web'
    if inferred!='web' and selected not in {'web',inferred}:raise ValueError("平台与链接不一致")
    if '://' in target:selected=inferred
    next_step=payload.get('next_step','').strip()
    if len(next_step)>2000:raise ValueError("下一步请控制在2000字内")
    return {'target':target,'label':title,'kind':kind,'reason':reason,'next_step':next_step or NEXT[kind],'platform':selected}


def seed_initial(data,stamp,pid=None):
    """Offer configured entry points once per project, never resurrect a deletion."""
    pid=project(data,pid)['id']
    templates=json.loads((Path(__file__).resolve().parent/'config/initial-leads.json').read_text(encoding='utf-8-sig'))
    templates+= [{'kind':'topic','title':word,'target':word,'reason':'本项目配置的种子搜索词，作为起始入口；后续由AI随证据调整。',
                  'next_step':'搜索公开内容，提取活动、机构、创作者等新线索。'} for word in project(data,pid).get('seed_keywords',[])]
    if not isinstance(templates,list) or not all(isinstance(r,dict) for r in templates):raise ValueError('默认初始线索配置需为对象数组')
    known={r['key'] for r in library(data,pid)+library(data,pid,deleted=True)}
    added=[]
    for template in templates:
        fields=_fields(template);key=identity(fields['target'],fields['platform'])
        if key in known:continue
        row={**fields,'id':uuid4().hex[:12],'project_id':pid,'origin':'seed','status':'new',
             'created_at':stamp,'last_seen_at':stamp,'run_id':None,
             'discovery_path':[{'label':'初始搜索入口','url':fields['target'] if fields['target'].startswith(('http://','https://')) else None,
                                'reason':'机会发现入口，尚未读取或核验其中具体活动。'}]}
        data['followups'].append(row);known.add(key);added.append(row['id'])
        _event(data,pid,stamp,'加入默认搜索入口：'+fields['label'],actor='seed')
    return {'added':added,'selection_policy':SELECTION_POLICY}


def _audit_context(data,payload,pid,actor):
    if actor not in {'manual','agent'}:raise ValueError('线索操作来源无效')
    run_id=payload.get('run_id')
    if run_id and not any(r['id']==run_id and r['project_id']==pid and r['status']=='running' for r in data['runs']):
        raise ValueError('线索操作须绑定当前项目的进行中轮次')
    return run_id


def _decision(payload):
    note=payload.get('decision')
    if not isinstance(note,str) or not note.strip() or len(note)>2000:raise ValueError('请记录本次线索取舍的理由（2000字内）')
    return note.strip()


def add_lead(files,payload,stamp,actor='manual'):
    fields=_fields(payload)
    def change(data):
        pid=project(data)['id'];key=identity(fields['target'],fields['platform'])
        run_id=_audit_context(data,payload,pid,actor)
        remember_links(data,payload,pid,stamp,actor+'_lead')
        if any(row['key']==key for row in library(data,deleted=True)):raise ValueError("这条入口已删除，可在已删除列表恢复")
        if any(row['key']==key for row in library(data)):raise ValueError("这条入口已在线索库中")
        row={**fields,'id':uuid4().hex[:12],'project_id':pid,'origin':actor,'status':'new',
             'created_at':stamp,'last_seen_at':stamp,'run_id':run_id}
        if payload.get('parent_url'):row['parent_url']=clean_target(payload['parent_url'])
        data['followups'].append(row)
        _event(data,pid,stamp,('AI' if actor=='agent' else '手动')+'添加搜索入口：'+fields['label']+'；'+fields['reason'],actor,run_id)
        return next(r for r in library(data) if r['key']==key)
    return files.change(change)


def update_lead(files,payload,stamp,actor='agent'):
    """Store discovery decisions as a followup; preserve original evidence/baselines."""
    note=_decision(payload)
    allowed={'id','run_id','decision','title','kind','reason','next_step','status'}
    if set(payload)-allowed:raise ValueError('仅可调整名称、类型、搜索价值、下一步和状态；新对象请新增线索')
    def change(data):
        pid=project(data)['id'];run_id=_audit_context(data,payload,pid,actor)
        entry=next((r for r in library(data) if r['id']==payload.get('id')),None)
        if not entry:raise ValueError('线索不存在、已删除或不属于当前项目')
        status=payload.get('status',entry['status'])
        if status not in STATUSES:raise ValueError('线索状态无效')
        fields=_fields({**entry,**{k:v for k,v in payload.items() if k in {'title','kind','reason','next_step'}}})
        row=next((r for r in data['followups'] if r['project_id']==pid and identity(r['target'],r['platform'])==entry['key']),None)
        if not row:
            row={**fields,'id':uuid4().hex[:12],'project_id':pid,'created_at':stamp,'origin':actor,
                 'run_id':run_id,'discovery_path':entry['discovery_path']}
            data['followups'].append(row)
        row.update({**fields,'status':status,'updated_at':stamp,'decision_at':stamp,'decision_note':note})
        _event(data,pid,stamp,('AI' if actor=='agent' else '手动')+'调整线索：'+fields['label']+'；'+note,actor,run_id)
        return next(r for r in library(data) if r['key']==entry['key'])
    return files.change(change)


def remove_lead(files,payload,stamp,restore=False,actor='manual'):
    note=_decision(payload) if actor=='agent' else ''
    def change(data):
        pid=project(data)['id'];run_id=_audit_context(data,payload,pid,actor)
        row=next((r for r in library(data,deleted=restore) if r['id']==payload.get('id')),None)
        if not row:raise ValueError("线索不存在或不属于当前项目")
        if restore and actor=='agent' and any(d.get('actor','manual')!='agent' for d in data['lead_deletions'] if d['project_id']==pid and d['key']==row['key']):
            raise ValueError('用户删除的入口须由用户恢复，AI不能自行恢复')
        if restore:data['lead_deletions']=[d for d in data['lead_deletions'] if not(d['project_id']==row['project_id'] and d['key']==row['key'])]
        else:data['lead_deletions'].append({'id':uuid4().hex[:12],'project_id':row['project_id'],'key':row['key'],'at':stamp,'origins':row['origins'],'actor':actor,'reason':note})
        _event(data,row['project_id'],stamp,('AI' if actor=='agent' else '手动')+('恢复' if restore else '删除')+'搜索入口：'+row['title']+('；'+note if note else ''),actor,run_id)
        return {'id':row['id'],'title':row['title'],'deleted':not restore}
    return files.change(change)


def _event(data,pid,stamp,message,actor='manual',run_id=None):
    data['events'].append({'id':uuid4().hex[:12],'project_id':pid,'at':stamp,'run_id':run_id,'item_id':None,'stage':'lead','message':message,'url':None,'actor':actor})


def annotate_deleted(data):
    refs={(r['collection'],r['id']) for entry in library(data,deleted=True) for r in entry['origins']}
    for collection in ('followups','sources','signals','items'):
        for row in data[collection]:row['discovery_disabled']=(collection,row['id']) in refs


def csv_text(data,cell,pid=None):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['项目','类型','名称','平台','搜索对象','为何值得继续','下一步','进度','添加方式','发现来源','更新时间','最近取舍理由','取舍时间'])
    for p in ([project(data,pid)] if pid else data['projects']):
        for row in library(data,p['id']):
            writer.writerow([cell(v) for v in [p['name'],row['kind_label'],row['title'],row['platform'],row['target'],row['reason'],row['next_step'],row['status'],row['origin'],' | '.join(n.get('url') or n.get('label','') for n in row['discovery_path']),row['updated_at'],row['decision_note'],row['decision_at']]])
    return stream.getvalue()
