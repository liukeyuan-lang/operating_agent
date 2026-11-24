"""Xiaohongshu home-feed notebook. The agent browses; this file never scrapes or clicks."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from file_store import file_lock

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / 'data' / 'homepage.json'
TZ = timezone(timedelta(hours=8))
ACTIVE = {'queued', 'running', 'stopping'}
COUNTS = ('refreshes', 'cards', 'details', 'kept', 'likes', 'collects')
DIMENSIONS={'traffic':'流量扶持','cash':'现金激励','commercial':'商业合作','exposure':'曝光增长','preferences':'用户偏好'}
DEFAULT_WEIGHTS={'traffic':30,'cash':25,'commercial':20,'exposure':15,'preferences':10}


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def text(value, name, maximum=20000, required=True):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(name + '格式不正确')
    return value.strip()


def instant(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('时间必须包含时区')
    return stamp


def url(value):
    value = text(value, '链接', 8000)
    p = urlsplit(value)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password or any(c.isspace() or ord(c)<32 for c in value) or '<redacted>' in value:
        raise ValueError('需要真实的 HTTP(S) 链接，不能使用脱敏占位符')
    p.port
    return value


def note_key(value):
    p = urlsplit(url(value))
    match = re.fullmatch(r'/(?:explore|discovery/item|search_result)/([a-f0-9]{24})', p.path.rstrip('/'))
    if p.hostname not in {'www.xiaohongshu.com', 'xiaohongshu.com'} or not match:
        raise ValueError('需要从小红书首页实际打开的笔记链接')
    return match[1]


def migrate(data):
    if data.get('version') not in {1,2}:raise ValueError('首页记录版本不支持')
    if data['version']==1:
        populated=any(data.get(k) for k in ('sessions','opportunities','observations'))
        data['projects']=[{'id':'legacy-homefeed','name':'首页探索','preferences':'','material_pack_ids':[],
                           'created_at':data.get('updated_at',now()),'updated_at':data.get('updated_at',now())}] if populated else []
        data['active_project_id']='legacy-homefeed' if populated else None
        for key in ('sessions','opportunities','observations'):
            for row in data.get(key,[]):row['project_id']='legacy-homefeed'
        data['version']=2
    data.pop('authors',None)
    for p in data['projects']:p.setdefault('weights',copy.deepcopy(DEFAULT_WEIGHTS))
    for row in data['opportunities']:
        row.pop('author',None);row.pop('identity',None)
        row.pop('asset_matches',None)
    return data


def project_for(data, identifier=None):
    identifier=identifier or data.get('active_project_id')
    row=next((p for p in data['projects'] if p['id']==identifier),None)
    if row is None:raise ValueError('探索项目不存在')
    return row


def project_packs(data, packs, identifier):
    ids=set(project_for(data,identifier).get('material_pack_ids',[]))
    return [p for p in packs if p['id'] in ids and not p.get('deleted')]


def material_ids(value, packs):
    if not isinstance(value,list) or any(not isinstance(v,str) for v in value):raise ValueError('项目素材需为素材包ID数组')
    valid={p['id'] for p in packs if not p.get('deleted')}
    if set(value)-valid:raise ValueError('选择的素材包不存在或已删除')
    return list(dict.fromkeys(value))


def score_weights(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_WEIGHTS):raise ValueError('需填写五项评分权重')
    result={}
    for key,number in value.items():
        if isinstance(number,str) and number.isascii() and number.isdigit():number=int(number)
        if type(number) is not int or not 0<=number<=100:raise ValueError('权重须为0至100的整数')
        result[key]=number
    if sum(result.values())!=100:raise ValueError('评分权重总和须为100')
    return result


def preference_digest(value):
    return hashlib.sha256(value.strip().encode()).hexdigest()


class FeedFiles:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    def load(self):
        if self.path.exists():
            return migrate(json.loads(self.path.read_text(encoding='utf-8-sig')))
        return {'version': 2, 'revision': 0, 'updated_at': now(), 'projects':[], 'active_project_id':None,
                'sessions': [], 'opportunities': [], 'observations': [], 'packets': []}

    def change(self, action):
        with file_lock(self.path):
            data = self.load()
            result = action(data)
            data['revision'] += 1
            data['updated_at'] = now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + '.' + uuid4().hex + '.tmp')
            try:
                with temporary.open('w', encoding='utf-8') as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=2)
                    stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            try:self.export(data)
            except OSError as error:
                if isinstance(result,dict):result['export_warning']='JSON已保存，导出暂未更新：'+str(error)
            return copy.deepcopy(result)

    def export(self, data=None, packs=None):
        data = data if data is not None else self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        view = notebook(data, [], '*')
        (self.path.parent / '首页探索记录.md').write_text(report(view), encoding='utf-8')
        (self.path.parent / '首页候选机会.csv').write_text(csv_text(view), encoding='utf-8-sig', newline='')
        (self.path.parent / '官方作者.json').unlink(missing_ok=True)


def session_for(data, identifier):
    row = next((s for s in data['sessions'] if s['id'] == identifier), None)
    if row is None:
        raise ValueError('首页探索任务不存在')
    return row


def prompt(identifier):
    return (f'请执行小红书首页探索任务 {identifier}。\n项目目录：{ROOT}\n'
            '先读取 AGENTS.md 和 skills/search-opportunity/SKILL.md，然后执行：\n'
            f'python homefeed.py task {identifier} --begin\n'
            '复用已登录的 Playwright MCP 浏览器，反复刷新小红书首页并阅读相关原帖。'
            '按任务中的项目偏好判断机会，使用项目保存的权重评分；不读取或考虑素材。点赞、收藏合适的原帖，绝不关注任何作者。'
            '不使用种子词或站内搜索替代首页探索。逐批保存进度，结束时导出首页探索记录。')


def create_session(files, payload, packs=None):
    packs=packs or []
    if payload.get('login_confirmed') is not True:
        raise ValueError('请先在 Playwright 专用浏览器登录所需的小红书账号')
    def action(data):
        mode=payload.get('mode') or ('continue' if data.get('active_project_id') else 'new')
        if mode not in {'new','continue'}:raise ValueError('请选择新建项目或继续旧项目')
        previous=project_for(data,payload.get('project_id')) if mode=='continue' else None
        name=text(payload.get('name',previous['name'] if previous else '新探索'),'项目名称',150,False) or '新探索'
        preferences=text(payload.get('preferences',previous.get('preferences','') if previous else ''),'偏好方向',10000,False)
        weights=score_weights(payload.get('weights',previous.get('weights',DEFAULT_WEIGHTS) if previous else DEFAULT_WEIGHTS))
        selected=material_ids(payload.get('material_pack_ids',previous.get('material_pack_ids',[]) if previous else []),packs)
        stamp=now()
        if previous:
            p=previous
        else:
            p={'id':uuid4().hex[:12],'created_at':stamp};data['projects'].append(p)
        p.update(name=name,preferences=preferences,weights=weights,material_pack_ids=selected,updated_at=stamp)
        data['active_project_id']=p['id']
        active = next((s for s in reversed(data['sessions']) if s['project_id']==p['id'] and s['status'] in ACTIVE), None)
        if active:
            return {**active, 'project':p, 'execution_prompt': prompt(active['id']), 'resumed': True}
        row = {'id': uuid4().hex[:10], 'status': 'queued', 'created_at': stamp, 'updated_at': stamp,
               'login_confirmed': True, 'allow_interactions': True, 'counts': {k: 0 for k in COUNTS},
               'summary': '', 'platform': 'xiaohongshu', 'method': 'homefeed','project_id':p['id']}
        data['sessions'].append(row)
        return {**row, 'project':p, 'execution_prompt': prompt(row['id']), 'resumed': False}
    return files.change(action)


def task(files, identifier, begin=False):
    if begin:
        def action(data):
            row = session_for(data, identifier)
            if row['status'] == 'queued':
                other=next((s for s in data['sessions'] if s['id']!=identifier and s['status'] in {'running','stopping'}),None)
                if other:raise ValueError('另一个任务仍在使用浏览器：'+other['id']+'，请先结束或停止该任务')
                row.update(status='running', started_at=now(), updated_at=now())
                data['active_project_id']=row['project_id']
            return row
        files.change(action)
    data = files.load(); row = session_for(data, identifier);pid=row['project_id']
    p=project_for(data,pid)
    return {'session': row, 'project':{k:p[k] for k in ('id','name','preferences','weights')},
            'next_action': 'stop' if row['status']=='stopping' else 'browse' if row['status']=='running' else 'begin' if row['status']=='queued' else 'report',
            'home_url': 'https://www.xiaohongshu.com/explore',
            'seen_notes': [{'note_id': o['note_id'], 'decision': o['decision'], 'reason': o['reason']} for o in data['observations'] if o['project_id']==pid],
            'opportunity_ids': [o['id'] for o in data['opportunities'] if o['project_id']==pid],
            'record_command': 'python homefeed.py record OBSERVATION.json',
            'report_path': str(files.path.parent/'首页探索记录.md')}


def select_project(files,identifier):
    def action(data):
        p=project_for(data,identifier);data['active_project_id']=p['id'];return p
    return files.change(action)


def attach_pack(files,identifier,pack_id,packs):
    def action(data):
        p=project_for(data,identifier)
        p['material_pack_ids']=material_ids([*p['material_pack_ids'],pack_id],packs)
        p['updated_at']=now();return p
    return files.change(action)


def detach_pack(files,identifier,pack_id):
    def action(data):
        p=project_for(data,identifier)
        if pack_id not in p['material_pack_ids']:raise ValueError('素材包不在当前项目中')
        p['material_pack_ids'].remove(pack_id);p['updated_at']=now();return p
    return files.change(action)


def stop_session(files, identifier):
    def action(data):
        row = session_for(data, identifier)
        if row['status']=='queued':
            row.update(status='interrupted', finished_at=now(), summary='用户停止，尚未执行浏览。')
        elif row['status']=='running':
            row.update(status='stopping', stop_requested_at=now())
        row['updated_at']=now()
        return row
    return files.change(action)


def finish(files, identifier, status, summary):
    if status not in {'completed', 'partial', 'blocked', 'interrupted'}:
        raise ValueError('未知结束状态')
    summary=text(summary, '结束说明', 6000)
    def action(data):
        row=session_for(data, identifier)
        if row['status'] not in ACTIVE:
            return row
        row.update(status='interrupted' if row['status']=='stopping' else status, summary=summary, finished_at=now(), updated_at=now())
        return row
    return files.change(action)


def documents(rows, stamp):
    if not isinstance(rows, list) or not rows:
        raise ValueError('候选需要实际读过的正文证据')
    result=[]
    for d in rows:
        if not isinstance(d, dict):raise ValueError('正文证据格式不正确')
        read_at=text(d.get('read_at'), '读取时间', 80)
        age=(instant(stamp)-instant(read_at)).total_seconds()
        if not -300 <= age <= 7*86400:
            raise ValueError('证据需要7天内实际读取的原文，不能使用未来时间')
        result.append({'id':text(d.get('id'), '证据ID', 100), 'url':url(d.get('url')),
                       'excerpt':text(d.get('excerpt'), '正文证据'), 'read_at':read_at,
                       'official':d.get('official') is True,
                       'authority_basis':text(d.get('authority_basis', ''), '官方身份依据', 2000, False)})
        if result[-1]['official'] and not result[-1]['authority_basis']:
            raise ValueError('标记官方原文必须说明身份依据')
    if len({d['id'] for d in result})!=len(result):raise ValueError('证据ID不能重复')
    return result


def proof_ok(value, docs, stamp):
    if not isinstance(value, dict) or not value.get('quote'):return False
    doc=next((d for d in docs if d['id']==value.get('source_id')), None)
    return bool(doc and doc['official'] and value['quote'] in doc['excerpt'] and
                0 <= (instant(stamp)-instant(doc['read_at'])).total_seconds() <= 7*86400)


def opportunity(payload, stamp, preferences):
    if 'asset_matches' in payload:raise ValueError('首页探索不读取或评估素材，请改为用户偏好评分')
    docs=documents(payload.get('evidence'), stamp)
    benefits=payload.get('benefits')
    if not isinstance(benefits, dict) or set(benefits)!=set(DIMENSIONS)-{'preferences'}:
        raise ValueError('需提供 traffic/cash/commercial/exposure 四项评分，未知填null')
    for row in benefits.values():
        if not isinstance(row, dict):raise ValueError('每项评分需要分数、理由和证据')
        score=row.get('score')
        text(row.get('reason'), '评分理由', 3000)
        if score is not None and (type(score) is not int or not 0<=score<=5 or not proof_ok(row.get('evidence'), docs, stamp)):
            raise ValueError('已知权益须为0至5整数分，并引用7天内实际读过的官方原文')
    status=payload.get('open_status', {})
    if status.get('value') not in {'open','unknown','closed'}:
        raise ValueError('开放状态须为open/unknown/closed')
    if status['value']!='unknown' and not proof_ok(status.get('evidence'), docs, stamp):
        raise ValueError('开放或关闭判断必须引用官方原文')
    deadline=payload.get('deadline', {})
    if not isinstance(deadline, dict):raise ValueError('截止时间格式不正确')
    if deadline.get('at'):
        instant(deadline['at'])
        if not proof_ok(deadline.get('evidence'), docs, stamp):raise ValueError('具体截止时间必须引用官方原文')
    unknowns=payload.get('uncertainties', [])
    if not isinstance(unknowns,list) or any(not isinstance(s,str) for s in unknowns):raise ValueError('未知条件需为文字数组')
    match=payload.get('preference_match',{'score':None,'reason':'偏好尚未评估' if preferences.strip() else '用户未填写偏好'})
    if not isinstance(match,dict):raise ValueError('用户偏好评分需含score和reason')
    score=match.get('score');text(match.get('reason'),'偏好评分理由',3000)
    if score is not None:
        if type(score) is not int or not 0<=score<=5:raise ValueError('用户偏好分须为0至5的整数，未知填null')
        if not preferences.strip():raise ValueError('用户未填写偏好，不能擅自加偏好分')
    return {'title':text(payload.get('title'), '机会名称', 300), 'summary':text(payload.get('summary'), '机会说明', 3000),
            'kind':text(payload.get('kind','合作机会'), '机会类型', 100),
            'evidence':docs, 'benefits':copy.deepcopy(benefits), 'open_status':copy.deepcopy(status),
            'deadline':copy.deepcopy(deadline), 'uncertainties':copy.deepcopy(unknowns),
            'requirements':text(payload.get('requirements',''), '参与条件', 6000, False),
            'rights':text(payload.get('rights','未确认'), '授权条件', 3000),
            'entry_url':url(payload['entry_url']) if payload.get('entry_url') else None,
            'preference_match':{**copy.deepcopy(match),'preferences_digest':preference_digest(preferences)}, 'assessed_at':stamp}


def interaction(row, note_id):
    if not isinstance(row, dict) or set(row)-{'status','before','after','evidence','at'}:
        raise ValueError('互动回执格式不正确；只允许点赞与收藏')
    if row.get('status') not in {'performed','already_done','failed','unknown','skipped'}:
        raise ValueError('互动状态不正确')
    if row['status'] in {'performed','already_done'}:
        if row.get('after') is not True or row.get('before') is not (row['status']=='already_done'):
            raise ValueError('成功互动需有真实的前后状态；已完成的不得重复点击')
        text(row.get('evidence'), '互动后可见状态', 3000)
    if row.get('at'):instant(row['at'])
    return copy.deepcopy(row)


def record(files, packet):
    stamp=now()
    packet_id=text(packet.get('packet_id'), '观察包ID', 100)
    digest=hashlib.sha256(json.dumps(packet,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if set(packet)-{'packet_id','session_id','refreshes','cards','notes','message'}:
        raise ValueError('观察包包含不支持的动作；此流程不允许关注作者')
    for key in ('refreshes','cards'):
        if type(packet.get(key,0)) is not int or packet.get(key,0)<0:raise ValueError('首页进度须为非负整数')
    notes=packet.get('notes', [])
    if not isinstance(notes,list):raise ValueError('笔记观察需为数组')
    def action(data):
        row=session_for(data, packet.get('session_id'))
        pid=row['project_id']
        preferences=project_for(data,pid).get('preferences','')
        existing=next((p for p in data['packets'] if p['id']==packet_id),None)
        if existing:
            if existing['digest']!=digest:raise ValueError('同一观察包ID不能改写内容，请使用新的ID')
            return {'duplicate':True, 'session':row}
        if row['status'] not in {'running','stopping'}:raise ValueError('任务未开始或已经结束，不能补造浏览进度')
        row['counts']['refreshes']+=packet.get('refreshes',0)
        row['counts']['cards']+=packet.get('cards',0)
        saved=[]
        for note in notes:
            if not isinstance(note,dict) or set(note)-{'url','title','decision','reason','opportunity','interactions','read_at'}:
                raise ValueError('笔记观察字段不正确')
            link=url(note.get('url')); key=note_key(link)
            read_at=text(note.get('read_at'), '笔记阅读时间', 80)
            if not -300<=(instant(stamp)-instant(read_at)).total_seconds()<=7*86400:raise ValueError('需要本次实际阅读的笔记时间')
            if note.get('decision') not in {'keep','skip'}:raise ValueError('笔记判断须为keep/skip')
            reason=text(note.get('reason'), '判断理由', 4000)
            title=text(note.get('title'), '原帖标题', 400)
            actions=note.get('interactions', {})
            if not isinstance(actions,dict) or set(actions)-{'like','collect'}:raise ValueError('只能记录点赞、收藏；不能关注作者')
            actions={k:interaction(v,key) for k,v in actions.items()}
            if any(a.get('status')=='performed' for a in actions.values()) and not row.get('allow_interactions'):
                raise ValueError('本任务未授权点赞收藏')
            previous=next((o for o in data['observations'] if o['project_id']==pid and o['note_id']==key),None)
            if previous is None:
                previous={'note_id':key,'project_id':pid,'first_seen_at':stamp,'sessions':[]};data['observations'].append(previous)
            if row['id'] not in previous['sessions']:previous['sessions'].append(row['id'])
            newly_read=previous.get('read_at')!=read_at
            previous.update(url=link,title=title,decision=note['decision'],reason=reason,read_at=read_at,updated_at=stamp)
            old_actions=previous.setdefault('interactions',{})
            for kind,receipt in actions.items():
                if receipt['status']=='performed' and old_actions.get(kind,{}).get('after') is not True:
                    row['counts']['likes' if kind=='like' else 'collects']+=1
                old_actions[kind]=receipt
            if newly_read:row['counts']['details']+=1
            if note['decision']=='keep':
                value=opportunity(note.get('opportunity',{}), stamp, preferences)
                if any(a.get('status')=='performed' for a in actions.values()) and (
                    value['open_status']['value']!='open' or not any(v.get('score',0) is not None and v.get('score',0)>0 for v in value['benefits'].values()) or
                    (value.get('deadline',{}).get('at') and instant(value['deadline']['at'])<=instant(stamp))):
                    raise ValueError('执行点赞收藏的机会需要当前开放和正向官方价值依据')
                current=next((o for o in data['opportunities'] if o['project_id']==pid and key in o['note_ids']),None)
                if current is None:
                    current={'id':uuid4().hex[:12],'project_id':pid,'note_ids':[],'first_seen_at':stamp,'sessions':[]}
                    data['opportunities'].append(current)
                if key not in current['note_ids']:current['note_ids'].append(key)
                if row['id'] not in current['sessions']:
                    current['sessions'].append(row['id']);row['counts']['kept']+=1
                current.update(value,url=link,updated_at=stamp,interactions=copy.deepcopy(old_actions))
                saved.append(current['id'])
            elif any(a.get('status')=='performed' for a in actions.values()):
                raise ValueError('跳过的内容不应执行点赞收藏')
        row.update(updated_at=stamp, last_message=text(packet.get('message','已保存首页观察'),'进度说明',2000))
        data['packets'].append({'id':packet_id,'digest':digest})
        return {'duplicate':False,'saved_ids':saved,'session':row}
    return files.change(action)


def rank(item, project, stamp):
    components=[];total=0;known=0
    weights=project.get('weights',DEFAULT_WEIGHTS)
    for key,label in DIMENSIONS.items():
        if key=='preferences':continue
        weight=weights[key]
        value=item['benefits'][key]
        score=value.get('score') if proof_ok(value.get('evidence'),item['evidence'],stamp) else None
        points=round(score*weight/5,1) if score is not None else 0
        components.append({'key':key,'label':label,'weight':weight,'score':score,'points':points,'reason':value['reason'],'evidence':value.get('evidence')})
        total+=points;known+=weight if score is not None else 0
    preferences=project.get('preferences','');match=item.get('preference_match',{})
    current=bool(preferences.strip()) and match.get('preferences_digest')==preference_digest(preferences)
    score=match.get('score') if current else None;weight=weights['preferences']
    points=round(score*weight/5,1) if score is not None else 0;total+=points;known+=weight if score is not None else 0
    components.append({'key':'preferences','label':'用户偏好','weight':weight,'score':score,'points':points,
                       'reason':match.get('reason','偏好尚未评估') if current else '用户未填写偏好' if not preferences.strip() else '偏好已更新，需重新评估'})
    state=item['open_status'];status=state['value'] if proof_ok(state.get('evidence'),item['evidence'],stamp) else 'unknown'
    if item.get('deadline',{}).get('at') and instant(item['deadline']['at'])<=instant(stamp):status='closed'
    return {'total':round(total,1),'known_weight':known,'status':status,'components':components}


def notebook(data, packs, project_id=None):
    result=copy.deepcopy(data)
    p=project_for(data,project_id) if project_id!='*' and data['projects'] else None
    if project_id and project_id!='*' and p is None:raise ValueError('探索项目不存在')
    for key in ('sessions','opportunities','observations'):
        if project_id!='*':result[key]=[r for r in result[key] if p and r['project_id']==p['id']]
    result['current_project']=copy.deepcopy(p)
    for row in result['opportunities']:
        row['project_name']=project_for(data,row['project_id'])['name']
        row['ranking']=rank(row,project_for(data,row['project_id']),now())
    result['opportunities'].sort(key=lambda r:(r['ranking']['status']=='closed',-r['ranking']['total'],r['id']))
    result['active_session']=next((s for s in reversed(result['sessions']) if s['status'] in ACTIVE),None)
    result['latest_session']=result['sessions'][-1] if result['sessions'] else None
    result['stats']={'opportunities':sum(r['ranking']['status']!='closed' for r in result['opportunities']),
                     'read_notes':len(result['observations'])}
    result.pop('packets',None)
    return result


def csv_text(view):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['项目','机会','总分','流量扶持','现金激励','商业合作','曝光增长','用户偏好','项目权重','开放状态','截止说明','来源','待确认'])
    for row in view['opportunities']:
        r=row['ranking'];values=[row['project_name'],row['title'],r['total'],*[c['points'] if c['score'] is not None else '未知' for c in r['components']],json.dumps({c['label']:c['weight'] for c in r['components']},ensure_ascii=False),r['status'],row.get('deadline',{}).get('label','未确认'),row['url'],'；'.join(row['uncertainties'])]
        writer.writerow(["'"+str(v) if str(v)[:1] in {'=','+','-','@','\t','\r'} else v for v in values])
    return stream.getvalue()


def report(view):
    lines=['# 小红书首页探索记录','',f"更新：{view['updated_at']}",'','来自已登录账号的首页推荐。未关注任何作者。分数使用各项目保存的权重；未知项不加分，不考虑素材。','']
    for p in view['projects']:
        if view.get('current_project') and p['id']!=view['current_project']['id']:continue
        lines += [f"项目：{p['name']}",'偏好：'+(p.get('preferences') or '未填写'), '权重：'+'、'.join(DIMENSIONS[k]+str(p['weights'][k]) for k in DIMENSIONS),'']
    for row in view['opportunities']:
        r=row['ranking'];lines += [f"## {row['title']} · {r['total']}/100",'',row['summary'],'',f"- 原帖：{row['url']}",f"- 状态：{r['status']}；截止：{row.get('deadline',{}).get('label','未确认')}"]
        lines.append('- 项目：'+row['project_name'])
        lines.append('- 互动：'+'；'.join(('点赞' if k=='like' else '收藏')+' '+a['status'] for k,a in row.get('interactions',{}).items()))
        lines+=['',*['- '+c['label']+'：'+(str(c['points'])+'/'+str(c['weight']) if c['score'] is not None else '未知')+'；'+c['reason'] for c in r['components']], '', '参与条件：'+row['requirements'], '授权：'+row['rights']]
        if row['entry_url']:lines.append('报名入口：'+row['entry_url'])
        lines+=['待确认：'+'；'.join(row['uncertainties']),'','原文证据：']
        for d in row['evidence']:lines+=['',f"- {d['url']}（{d['read_at']}；{'官方' if d['official'] else '转述'}）",'> '+d['excerpt'].replace('\n','\n> ')]
        lines.append('')
    if not view['opportunities']:lines+=['本轮尚未记录候选机会。','']
    lines+=['## 浏览进度','']
    names={p['id']:p['name'] for p in view['projects']}
    for s in view['sessions']:lines.append(f"- {names[s['project_id']]} · {s['id']} · {s['status']} · {json.dumps(s['counts'],ensure_ascii=False)} · {s.get('summary') or s.get('last_message','等待执行')}")
    skipped=[o for o in view['observations'] if o['decision']=='skip']
    if skipped:lines+=['','## 未保留的原帖','',*[f"- {o['title']}：{o['reason']} · {o['url']}" for o in skipped]]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description='小红书首页探索记录，不在后台自动浏览')
    parser.add_argument('--data',default=str(DEFAULT_PATH));sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status');sub.add_parser('export')
    start=sub.add_parser('start');start.add_argument('--logged-in',action='store_true')
    start.add_argument('--allow-interactions',action='store_true',help=argparse.SUPPRESS)
    start.add_argument('--project-id');start.add_argument('--new',action='store_true');start.add_argument('--name');start.add_argument('--preferences')
    get=sub.add_parser('task');get.add_argument('id');get.add_argument('--begin',action='store_true')
    save=sub.add_parser('record');save.add_argument('file')
    stop=sub.add_parser('stop');stop.add_argument('id')
    end=sub.add_parser('finish');end.add_argument('id');end.add_argument('--status',choices=['completed','partial','blocked','interrupted'],default='completed');end.add_argument('--summary',required=True)
    args=parser.parse_args();files=FeedFiles(args.data)
    try:
        workspace=files.path.parent/'workspace.json'
        packs=json.loads(workspace.read_text(encoding='utf-8')).get('material_packs',[]) if args.command=='start' and workspace.exists() else []
        if args.command=='start':
            payload={'login_confirmed':args.logged_in}
            if args.new:payload['mode']='new'
            if args.project_id:payload.update(mode='continue',project_id=args.project_id)
            if args.name is not None:payload['name']=args.name
            if args.preferences is not None:payload['preferences']=args.preferences
            result=create_session(files,payload,packs)
        elif args.command=='task':result=task(files,args.id,args.begin)
        elif args.command=='record':result=record(files,json.loads(Path(args.file).read_text(encoding='utf-8-sig')))
        elif args.command=='stop':result=stop_session(files,args.id)
        elif args.command=='finish':result=finish(files,args.id,args.status,args.summary)
        elif args.command=='export':files.export(packs=packs);result={'report':str(files.path.parent/'首页探索记录.md')}
        else:result=notebook(files.load(),packs)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
