"""File-backed opportunity demo. Codex reads pages; Python stores and displays."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, quote
from uuid import uuid4
from platforms import PLATFORMS,platform,discovery_platform_list,discovery_catalog,detect_platform,content_url
from research import catalog,export_research,record_check,record_snapshot
from verification import team_input,refresh_checks,tasks as verification_tasks
from opportunities import related_links as opportunity_links
from access_links import remember_links,url_map,resolve_url,annotate_links,save_links
from file_store import file_lock
from file_picker import browse_directories,pick_files,pick_directory
from material_understanding import MaterialService,asset_metadata,request_timeout_seconds,MODEL as MATERIAL_MODEL
from project_workspaces import ProjectFiles,workspace_project
from discovery import DEFAULT_REQUIREMENTS,DEFAULT_SEEDS,seeds,rank_candidate,save_assessment,DIMENSIONS as RANK_DIMENSIONS
from material_library import add_pack,delete_pack,view_packs
from leads import (KINDS as LEAD_KINDS, FOLLOWUP_KINDS, STATUSES as LEAD_STATUSES,
                   SELECTION_POLICY, library, add_lead, update_lead, remove_lead, seed_initial,
                   annotate_deleted, clean_target, identity as lead_identity, csv_text as leads_csv)
from workflow import PLAN, COUNTERS, GATES, classify, coverage, migrate, project, profile_digest, scoped, search_limit
import homefeed
import share_page
from media import inspect_mp4, local_available
from planning import (DIMENSIONS, next_week, package_markdown, plan_view, planning_csv,
                      record_signals, review_action, save_plan, signal_state)
from publishing import (approve_job, create_job, edit_job, export_publications, generate_cover,
                        job_for, package_text, package_zip, record_execution, request_draft, view_job)

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "workspace.json"
TZ = timezone(timedelta(hours=8))
FACTS = {"eligibility":"报名资格", "ai_policy":"AI作品政策", "deadline":"截止时间",
         "attendance":"到场要求", "fees":"费用", "formats":"作品规格",
         "rights":"首发与授权", "rewards":"奖励与资源", "entry_url":"报名入口","open_status":"当前开放状态"}


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def canonical(value):
    p = urlsplit(value.strip())
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("请填写不带账号密码的 HTTP(S) 链接")
    drop = {"xsec_token","xsec_source","source","s","ref","fbclid"}
    params = [(k,v) for k,v in parse_qsl(p.query) if k not in drop and not k.startswith("utm_")]
    path=p.path.rstrip("/") or "/"
    if (p.hostname=="xiaohongshu.com" or p.hostname.endswith(".xiaohongshu.com")):
        match=re.fullmatch(r"/(?:search_result|explore)/([a-f0-9]{24})",path)
        if match: path="/explore/"+match[1]
    if detect_platform(value) in PLATFORMS:
        try:return content_url(value)
        except ValueError:pass
    return urlunsplit((p.scheme,p.netloc.lower(),path,urlencode(sorted(params)),""))


def blank():
    config = read(ROOT/"config/project.json")
    return migrate({"schema_version":2,"revision":0,"updated_at":now(),
            "project":config["project"],"team":config["team"],"assets":config["assets"],
            "requests":[],"runs":[],"items":[],"sources":[],"followups":[],"events":[]})


class Files:
    def __init__(self,path=STATE_PATH):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return blank()
        data = read(self.path)
        return migrate(data)

    def change(self, action):
        with file_lock(self.path):
            data = self.load()
            result = action(data)
            refresh_checks(data,now())
            data["revision"] += 1
            data["updated_at"] = now()
            self.path.parent.mkdir(parents=True,exist_ok=True)
            if self.path.exists():
                self.path.with_suffix(".json.bak").write_bytes(self.path.read_bytes())
            temp = self.path.with_name(self.path.name + "." + uuid4().hex + ".tmp")
            try:
                with open(temp,"w",encoding="utf-8") as stream:
                    json.dump(data,stream,ensure_ascii=False,indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp,self.path)
            finally:
                temp.unlink(missing_ok=True)
            try:
                self.export(data)
            except OSError as error:
                if isinstance(result,dict):
                    result["csv_warning"]="JSON已保存，但CSV暂未更新（可能在Excel中打开）："+str(error)
            return result

    def export(self,data=None):
        data = data or self.load()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        export_publications(data,self.path.parent,csv_cell)
        export_research(data,self.path.parent,csv_cell)
        with open(self.path.parent/"机会核验.csv","w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream);writer.writerow(['项目','机会','状态','最近检查','实际查证时间','核验说明','剩余问题'])
            for item in data['items']:
                v=item.get('verification',{})
                writer.writerow([csv_cell(x) for x in [project(data,item['project_id'])['name'],item['title'],v.get('status'),v.get('checked_at'),v.get('last_attempt_at'),v.get('attempt_note'),'；'.join(v.get('issues',[]))]])
        (self.path.parent/"搜索线索.csv").write_text(leads_csv(data,csv_cell),encoding="utf-8-sig",newline="")
        (self.path.parent/"机会清单.csv").write_text(csv_text(data),encoding="utf-8-sig",newline="")
        with open(self.path.parent/'候选机会评分.csv','w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['项目','机会','总分','已知依据权重%','候选状态','待确认事项','来源','分项评分'])
            ranked=[(i,rank_candidate(i,project(data,i['project_id']),data['material_packs'],now())) for i in data['items'] if not i.get('discovery_disabled')]
            for i,r in sorted(ranked,key=lambda pair:(pair[1]['total'] is None,-(pair[1]['total'] or 0),pair[0]['id'])):
                writer.writerow([csv_cell(v) for v in [project(data,i['project_id'])['name'],i['title'],r['total'],r['known_weight'],r['status'],'；'.join(r['issues']),i['url'],json.dumps(r['components'],ensure_ascii=False)]])
        with open(self.path.parent/'素材库.csv','w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['素材包ID','名称','目录','理解版本','文件数','已删除'])
            for pack in data['material_packs']:writer.writerow([csv_cell(v) for v in [pack['id'],pack['name'],pack.get('directory'),pack.get('analysis_id'),len(pack['assets']),pack.get('deleted',False)]])
        (self.path.parent/"每周行动卡.csv").write_text(planning_csv(data,csv_cell),encoding="utf-8-sig",newline="")
        with open(self.path.parent/"话题与内容观察.csv","w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream)
            writer.writerow(["项目","平台","观察","类型","热度证据状态","与项目关系","证据链接","最近保存"])
            for s in data["signals"]:
                writer.writerow([csv_cell(v) for v in [project(data,s["project_id"])["name"],PLATFORMS.get(s["platform"],{"name":"网页"})["name"],s["title"],s["kind"],signal_state(s),s["fit_reason"],
                                                       " | ".join(e["url"] for e in s["evidence"]),s["updated_at"]]])
        for p in data["projects"]:
            view=plan_view(scoped(data,p["id"]))
            if view:
                directory=self.path.parent/"plans"/view["id"]
                directory.mkdir(parents=True,exist_ok=True)
                for a in view["actions"]:
                    (directory/(a["key"]+".md")).write_text(package_markdown(view,a),encoding="utf-8")
        for bucket,name in (("result","可参加结果"),("lead","待核验线索"),("archive","历史与排除")):
            part=copy.deepcopy(data)
            part["items"]=[i for i in part["items"] if (classify(i,project(data,i["project_id"]))[0]==bucket
                          if bucket!="archive" else classify(i,project(data,i["project_id"]))[0] in {"excluded","history"})]
            (self.path.parent/(name+".csv")).write_text(csv_text(part),encoding="utf-8-sig",newline="")
        with open(self.path.parent/"观察清单.csv","w",encoding="utf-8-sig",newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["名称","平台","角色","链接","关注原因","阶段相似性","最近检查","已见帖子数"])
            for s in data["sources"]:
                writer.writerow([csv_cell(v) for v in [s["name"],PLATFORMS.get(s["platform"],{"name":"网页"})["name"],s["role"],s["url"],s["reason"],s.get("similarity_note","未知"),
                                 s.get("last_checked_at") or "未检查",len(s.get("seen_posts",[]))]])


def csv_cell(value):
    text = str(value if value is not None else "未核实")
    return "'"+text if text[:1] in {"=","+","-","@","\t","\r"} else text


def csv_text(data):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["探索项目","平台","分类","名称","状态","匹配判断","发现来源","官方来源","截止说明","未知条件","人工标记","首次发现","最近更新"])
    for item in data["items"]:
        p=project(data,item["project_id"])
        visits=url_map(data,p['id'])
        bucket,_=classify(item,p)
        writer.writerow([csv_cell(v) for v in [p["name"],PLATFORMS.get(item["platform"],{"name":"网页"})["name"],{"result":"可参加结果","lead":"待核验线索","excluded":"已排除","history":"历史线索"}[bucket],
                         item["title"],evidence_state(item),item.get("fit_reason"),resolve_url(item["url"],visits),
                         " | ".join(resolve_url(s["url"],visits) for s in item.get("official_sources",[])),
                         item.get("facts",{}).get("deadline",{}).get("value"),"；".join(unknowns(item)),
                         item["review"]["status"],item["first_seen_at"],item["updated_at"]]])
    return stream.getvalue()


def event(data,run_id,stage,message,url=None,item_id=None):
    run=next((r for r in data["runs"] if r["id"]==run_id),None)
    item=next((i for i in data["items"] if i["id"]==item_id),None)
    row = {"id":uuid4().hex[:12],"at":now(),"run_id":run_id,"stage":stage,"message":message,
           "url":canonical(url) if url else None,"item_id":item_id,
           "project_id":run["project_id"] if run else item["project_id"] if item else data["active_project_id"]}
    data["events"].append(row)
    return row


def material_binding(files,payload,service=None):
    directory=payload.get('material_directory');analysis_id=payload.get('material_analysis_id')
    if not directory or not analysis_id:raise ValueError('请选择素材目录并先完成Gemini理解')
    own=service is None
    service=service or MaterialService(files.path.parent/'materials.json')
    try:
        binding=service.bind(directory,analysis_id)
        binding['metadata']=[asset_metadata(entry) for entry in binding['files']]
        if any(m['version']!='sha256:'+entry['sha256'] for m,entry in zip(binding['metadata'],binding['files'])):raise ValueError('素材已变化，请重新理解')
        return binding
    finally:
        if own:service.close()


def apply_material_binding(data,p,binding):
    brief=binding['understanding']['description']
    if binding['understanding']['uncertainties']:brief+='\n待确认：'+'；'.join(binding['understanding']['uncertainties'])
    p['assets_brief']=brief
    wanted=set()
    for metadata in binding['metadata']:
        wanted.add(metadata['locator'])
        old=next((a for a in p['asset_references'] if a['locator']==metadata['locator']),None)
        if not old or old['version']!=metadata['version'] or old.get('file_signature')!=metadata['file_signature']:
            _register_asset(data,p,metadata)
    p['asset_references']=[a for a in p['asset_references'] if a['locator'] in wanted]
    p['assets_brief']=brief
    p['materials']={k:binding[k] for k in ['directory','analysis_id','fingerprint']}
    p['materials'].update(file_count=len(binding['files']),model=MATERIAL_MODEL)


def create_publishing_project(files,payload,service=None):
    binding=material_binding(files,payload,service)
    for key,limit in [('name',200),('description',10000)]:
        if not isinstance(payload.get(key,''),str) or len(payload.get(key,''))>limit:raise ValueError('项目名称或描述无效')
    def action(data):
        p={'id':uuid4().hex[:10],'workspace':'publishing','name':payload.get('name','').strip() or binding['understanding']['title'],
           'direction':payload.get('description','').strip() or binding['understanding']['description'],
           'assets_brief':'','resources_brief':'','team_profile':{},'asset_references':[],
           'discovery_platforms':['xiaohongshu','douyin'],'created_at':now(),'updated_at':now(),
           'auto_fields':{'name':not payload.get('name','').strip(),'description':not payload.get('description','').strip()}}
        data['projects'].append(p);apply_material_binding(data,p,binding)
        data['active_publishing_project_id']=p['id']
        return p
    return files.change(action)


def exploration_execution_prompt(files,request_id):
    data_note=''
    if files.path.resolve()!=STATE_PATH.resolve():
        data_note='\n任务数据文件：'+str(files.path.resolve())+'\n此任务使用自定义数据文件，运行下面命令时请在 demo.py 后添加 --data 参数并指定此文件。\n'
    return ('请执行已保存的探索任务 '+request_id+'。\n\n项目目录：'+str(ROOT)+data_note+
            '\n\n先阅读该目录下的 AGENTS.md 和 skills/search-opportunity/SKILL.md，然后在该目录执行：\n'
            'python demo.py task '+request_id+' --begin\n\n'
            '按任务记录中的探索要求、种子词、平台和历史继续，使用现有 Playwright MCP 进行真实搜索、动态扩展线索、观察同行、核验官方条件并给候选机会评分排序，持续保存进度和结果。'
            '请实际执行探索，不要只给计划，也不要重新创建任务。已开始的任务继续原轮次，已结束的任务读取并汇报已有结果。报名、付款、发布和对外联系仍须人工确认。')


def request_run(files,payload,service=None):
    if not isinstance(payload,dict): raise ValueError("请提供探索要求与种子词的JSON对象")
    def action(data):
        mode=payload.get("mode","continue")
        if mode not in {"new","continue"}: raise ValueError("请选择继续项目或新建项目")
        if mode=="new":
            p={"id":uuid4().hex[:10],"workspace":"exploration","created_at":now(),'name':'新探索','direction':DEFAULT_REQUIREMENTS,
               'assets_brief':'','resources_brief':'','asset_references':[],'discovery_version':2}
            data["projects"].append(p)
        else: p=project(data,payload.get("project_id"))
        if p.get('workspace','exploration')!='exploration':raise ValueError('发布项目不能创建探索任务')
        for key in ("name","resources_brief"):
            if key in payload:
                text=payload[key].strip()
                if len(text)>10000 or (key!="resources_brief" and not text): raise ValueError("项目资料为空或过长")
                p[key]=text
        requirements=payload.get('exploration_requirements',payload.get('direction',p.get('exploration_requirements',DEFAULT_REQUIREMENTS)))
        if not isinstance(requirements,str) or not requirements.strip() or len(requirements)>10000:raise ValueError('请填写探索要求，最多10000字')
        p['exploration_requirements']=requirements.strip();p['direction']=p['exploration_requirements']
        p['seed_keywords']=seeds(payload.get('seed_keywords',p.get('seed_keywords',DEFAULT_SEEDS)))
        p['max_searches']=search_limit(payload.get('max_searches',p.get('max_searches',PLAN['limits']['searches'])))
        p.pop('materials',None);p['asset_references']=[];p['assets_brief']=''
        p['team_profile']=team_input(payload,p.get('team_profile',{}))
        p.setdefault('asset_references',[])
        p["updated_at"]=now()
        p["discovery_platforms"]=discovery_platform_list(payload.get("platforms",p.get("discovery_platforms",["xiaohongshu"])))
        data["active_project_id"]=p["id"]
        seed_initial(data,now(),p['id'])
        row = {"id":uuid4().hex[:10],"project_id":p["id"],"mode":mode,"query":p["name"]+" · 候选机会探索",
               "status":"waiting_codex","created_at":now(),"profile_snapshot":copy.deepcopy(p),"platforms":p["discovery_platforms"]}
        row['auto_verify']=bool(payload.get('auto_verify',False))
        row['max_searches']=p['max_searches']
        data["requests"].append(row)
        event(data,None,"request",("继续探索：" if mode=="continue" else "新建独立探索项目：")+p["name"]+"；检索词和后续线索由Agent自主选择")
        return row
    request=files.change(action)
    return {**request,'execution_prompt':exploration_execution_prompt(files,request['id'])}

def select_project(files,pid,workspace='exploration'):
    def action(data):
        p=workspace_project(data,workspace,pid)
        data['active_publishing_project_id' if workspace=='publishing' else 'active_project_id']=p['id']
        return p
    return files.change(action)

def start_run(files,query=None,request_id=None,project_id=None):
    def action(data):
        if any(r["status"]=="running" for r in data["runs"]):
            raise ValueError("已有进行中的收集；请先完成它，或用 finish 标为 interrupted 后继续")
        request = next((r for r in data["requests"] if r["id"]==request_id),None) if request_id else None
        if request_id and (not request or request["status"]!="waiting_codex"):
            raise ValueError("待执行请求不存在或已处理")
        p=project(data,request["project_id"] if request else project_id)
        if p.get('workspace','exploration')!='exploration':raise ValueError('发布项目不执行机会探索')
        data['active_project_id']=p['id']
        seed_initial(data,now(),p['id'])
        topic = p["name"]+" · 候选机会探索"
        selected=discovery_platform_list(request["platforms"] if request else p["discovery_platforms"])
        max_searches=search_limit(request['max_searches'] if request else p.get('max_searches',PLAN['limits']['searches']))
        row = {"id":uuid4().hex[:10],"query":topic,"status":"running","stage":"discover",
               "project_id":p["id"],"profile_snapshot":copy.deepcopy(p),"profile_digest":profile_digest(p),
               "started_at":now(),"finished_at":None,"summary":None,"request_id":request_id,
               "limits":{'searches':max_searches},"counts":{k:0 for k in COUNTERS},"packet_ids":[],
               "targets":{},"platforms":selected,"scenario":"opportunity_discovery",
               "search_queries":[],
               "checked_source_urls":[],"read_post_urls":[],
               "new_items":0,"updated_items":0,"new_peer_posts":0,
               "execution":"当前 Codex 对话 + 已连接浏览器；网页本身不启动 Agent"}
        data["runs"].append(row)
        row['auto_verify']=bool(request and request.get('auto_verify'))
        if request: request["status"]="running"
        event(data,row["id"],"discover","开始候选机会探索："+p["name"]+"；依据探索要求和种子词，结合历史线索与同行继续搜索")
        return row
    return files.change(action)


def unknowns(item):
    facts = item.get("facts",{})
    missing = [label+"未核实" for key,label in FACTS.items() if not facts.get(key) or facts[key].get("status")!="confirmed"]
    missing += item.get("open_questions",[])
    return list(dict.fromkeys(missing))


def evidence_state(item):
    if item.get("historical") and not item.get("official_sources"):
        return "历史参展线索"
    if item.get("excluded_reason"):
        return "不适合"
    if item.get("official_sources"):
        return "关键条件已核实" if not unknowns(item) else "已找到原始公告"
    return "已读原帖" if item.get("read_at") else "仅有线索"


def validate_item(raw):
    item = copy.deepcopy(raw)
    for key in ("id","first_seen_at","updated_at","run_ids","review","changes","assessment","ranking"):
        item.pop(key,None)
    if not item.get("title") or not item.get("fit_reason"):
        raise ValueError("候选需有标题及与项目的匹配解释")
    item["url"] = canonical(item['url']) if detect_platform(item['url'])=='web' else content_url(item["url"],item.get("platform"))
    item["platform"]=detect_platform(item["url"])
    if item.get("author_url"): item["author_url"]=canonical(item["author_url"])
    if item.get("fit") not in {"strong","possible","weak"}:
        raise ValueError("匹配判断为 strong / possible / weak")
    sources = {}
    for doc in item.setdefault("official_sources",[]):
        for key in ("id","url","read_at","authority_basis","excerpt"):
            if not doc.get(key): raise ValueError("官方来源缺少 "+key)
        doc["url"] = canonical(doc["url"])
        moment=datetime.fromisoformat(doc["read_at"])
        if moment.tzinfo is None: raise ValueError("读取时间需包含时区")
        if doc["id"] in sources: raise ValueError("官方来源 id 重复")
        sources[doc["id"]]=doc
    for key,fact in item.setdefault("facts",{}).items():
        if key not in FACTS or fact.get("status") not in {"confirmed","uncertain"}:
            raise ValueError("未知事实字段或状态")
        doc = sources.get(fact.get("source_id"))
        if not doc or not fact.get("evidence") or fact["evidence"] not in doc["excerpt"]:
            raise ValueError("事实必须关联实际读取的官方来源及存在于摘录中的短证据")
        if not fact.get("value"):
            raise ValueError("未知值请省略，不得用空值表示已确认")
        if key=="deadline" and fact["status"]=="confirmed" and not fact.get("at") and fact.get("kind")!="rolling":
            raise ValueError("只有日期而无具体时刻/时区，截止必须标为 uncertain")
        if key=="deadline" and fact.get("at") and datetime.fromisoformat(fact["at"]).tzinfo is None:
            raise ValueError("截止时刻需包含时区")
    if item.get("participation"):
        check=item["participation"]
        if not isinstance(check,dict) or not check.get("profile_digest") or not check.get("checked_at"):
            raise ValueError("适配核验需绑定项目资料摘要与核验时间")
        if datetime.fromisoformat(check["checked_at"]).tzinfo is None:raise ValueError("适配核验时间需有时区")
        for key in GATES:
            gate=check.get(key,{})
            if gate.get("status") not in {"pass","fail","unknown"} or not gate.get("reason"):
                raise ValueError("资格、素材、权属与资源各需明确判断及理由")
    if not isinstance(item.get("open_questions",[]),list): raise ValueError("open_questions 需为列表")
    return item


def record(files,packet):
    if not packet.get("id") or not packet.get("run_id"):
        raise ValueError("记录包需有唯一 id 与 run_id")
    def action(data):
        run = next((r for r in data["runs"] if r["id"]==packet["run_id"]),None)
        if not run: raise ValueError("收集轮次不存在")
        signature=hashlib.sha256(json.dumps(packet,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
        if packet["id"] in run["packet_ids"]:
            previous=run.get("packet_hashes",{}).get(packet["id"])
            if previous and previous!=signature: raise ValueError("同一个记录包 id 已保存了不同内容，请使用新 id 补充")
            return {"status":"already_saved","run_id":run["id"]}
        if run["status"]!="running": raise ValueError("本轮已结束；请创建新轮次继续，历史不会清空")
        remember_links(data,packet,run['project_id'],now(),'observation')
        for key,value in packet.get("counts",{}).items():
            if key not in COUNTERS or type(value) is not int or value<0: raise ValueError("无效读取计数")
        added_searches=packet.get('counts',{}).get('searches',0)
        if added_searches and run['counts']['searches']+added_searches>run['limits']['searches']:
            raise ValueError('本轮最多搜索'+str(run['limits']['searches'])+'次，已用'+str(run['counts']['searches'])+'次；不能继续发起搜索，可继续读取、核验和评分已发现的内容')
        items = [validate_item(i) for i in packet.get("items",[])]
        record_signals(data,run,packet.get("signals",[]),now())
        for item in items:
            old = next((i for i in data["items"] if i["url"]==item["url"] and i["project_id"]==run["project_id"]),None)
            item["project_id"]=run["project_id"]
            stamp = now()
            if old:
                review = old["review"]
                run_ids = list(dict.fromkeys(old["run_ids"]+[run["id"]]))
                incoming_facts = {**old.get("facts",{}),**item.get("facts",{})}
                old_docs = {d["id"]:d for d in old.get("official_sources",[])}
                for d in item.get("official_sources",[]): old_docs[d["id"]]=d
                paths = old.get("discovery_path",[]) + [p for p in item.get("discovery_path",[]) if p not in old.get("discovery_path",[])]
                meaningful = any(old.get(k)!=item[k] for k in ("summary","fit_reason","facts","excluded_reason") if k in item)
                old.update(item)
                old.update({"review":review,"run_ids":run_ids,"facts":incoming_facts,"official_sources":list(old_docs.values()),
                            "discovery_path":paths,"updated_at":stamp})
                if meaningful:
                    old.setdefault("changes",[]).append({"at":stamp,"run_id":run["id"],"note":"重读补充了正文、核验或匹配判断；查看本轮原始记录包"})
                    run["updated_items"]+=1
                item_id=old["id"]
            else:
                item.update({"id":uuid4().hex[:10],"first_seen_at":stamp,"updated_at":stamp,
                             "run_ids":[run["id"]],"review":{"status":"new","note":""},"changes":[]})
                data["items"].append(item)
                run["new_items"]+=1
                item_id=item["id"]
            event(data,run["id"],"result","已保存："+item["title"],item["url"],item_id)
        for raw in packet.get("sources",[]):
            source=copy.deepcopy(raw)
            source["url"]=canonical(source["url"])
            source["platform"]=detect_platform(source["url"])
            if source.get("role") not in {"peer","organizer","information"} or not source.get("reason") or not source.get("name"):
                raise ValueError("观察来源需有名称、角色、关注原因")
            source["project_id"]=run["project_id"]
            old=next((s for s in data["sources"] if s["url"]==source["url"] and s["project_id"]==run["project_id"]),None)
            posts=list(dict.fromkeys(canonical(p) for p in source.get("seen_posts",[])))
            new_posts=[p for p in posts if not old or p not in old.get("seen_posts",[])]
            if source.get("checked_at") and source["role"]=="peer": run["new_peer_posts"]+=len(new_posts)
            if packet.get("counts",{}).get("source_checks",0)>0 and source.get("checked_at") and source["url"] not in run.setdefault("checked_source_urls",[]):
                run["checked_source_urls"].append(source["url"])
            if old:
                seen=list(dict.fromkeys(old.get("seen_posts",[])+posts))
                previous_checked=old.get("last_checked_at")
                old.update(source)
                old["seen_posts"]=seen
                old["last_checked_at"]=source.get("checked_at") or previous_checked
                old["new_posts_last_check"]=new_posts if source.get("checked_at") else old.get("new_posts_last_check",[])
            else:
                source.update({"id":uuid4().hex[:10],"added_at":now(),"last_checked_at":source.get("checked_at"),
                               "seen_posts":posts,"new_posts_last_check":new_posts})
                data["sources"].append(source)
        for raw in packet.get("followups",[]):
            follow=copy.deepcopy(raw)
            if follow.get('status') and follow['status'] not in LEAD_STATUSES:raise ValueError('线索状态无效')
            if not follow.get("target") or not follow.get("reason") or follow.get("kind") not in FOLLOWUP_KINDS:
                raise ValueError("后续线索需说明对象、类型及从哪里发现/为何值得继续")
            follow["target"]=clean_target(follow["target"])
            follow["platform"]=detect_platform(follow["target"]) if '://' in follow["target"] else platform(follow["platform"])["id"] if follow.get("platform") and follow["platform"]!="web" else detect_platform(follow.get("parent_url") or follow["target"])
            follow["project_id"]=run["project_id"]
            old=next((f for f in data["followups"] if f["project_id"]==run["project_id"] and lead_identity(f["target"],f["platform"])==lead_identity(follow["target"],follow["platform"])),None)
            if old:
                old["last_seen_at"]=now()
                if follow.get("status"): old["status"]=follow["status"]
            else:
                follow.update({"id":uuid4().hex[:10],"status":follow.get("status","new"),"created_at":now(),"last_seen_at":now(),"run_id":run["id"]})
                if follow.get("parent_url"): follow["parent_url"]=canonical(follow["parent_url"])
                data["followups"].append(follow)
        for raw in packet.get("events",[]):
            event(data,run["id"],raw.get("stage","explore"),raw["message"],raw.get("url"))
        for key,value in packet.get("counts",{}).items(): run["counts"][key]+=value
        post_reads=packet.get("counts",{}).get("post_reads",0)
        if post_reads and not run.get("legacy_demo"):
            post_urls=packet.get("read_post_urls",[i["url"] for i in items if i.get("read_at")])
            if len(post_urls)!=post_reads:raise ValueError("正文读取次数需对应实际读过的URL列表read_post_urls")
            for url in post_urls:
                url=canonical(url) if detect_platform(url)=='web' else content_url(url)
                if detect_platform(url) not in run["platforms"]:raise ValueError("正文阅读平台不在本轮选择范围内")
                run.setdefault("read_post_urls",[]).append(url)
        queries=copy.deepcopy(packet.get("queries",[]))
        if packet.get("counts",{}).get("searches",0)!=len(queries) and not run.get("legacy_demo"):
            raise ValueError("每次搜索都需记录实际query、渠道和选择理由；次数应一致")
        for q in queries:
            if any(not isinstance(q.get(k),str) or not q[k].strip() for k in ("query","reason","channel")):
                raise ValueError("搜索记录需说明query、reason和channel")
            q.pop('direction',None)
            if q["channel"]!="web":
                pconfig=platform(q["channel"])
                if pconfig["id"] not in run["platforms"]:raise ValueError("本轮未选择该平台；不能混入其他平台的搜索次数")
                q["channel"]=pconfig["channel"]
            if run.get("scenario")=="weekly_planning" and q.get("focus") not in {"topics","peers","opportunities"}:
                raise ValueError("场景B搜索需注明focus：topics / peers / opportunities")
            run["search_queries"].append(q)
        run["stage"]=packet.get("stage",run["stage"])
        run["packet_ids"].append(packet["id"])
        run.setdefault("packet_hashes",{})[packet["id"]]=signature
        remaining=max(0,run['limits']['searches']-run['counts']['searches'])
        return {"status":"saved","run_id":run["id"],"counts":run["counts"],"limit_exceeded":[],
                'searches_remaining':remaining,'search_budget_reached':remaining==0}
    return files.change(action)


def finish(files,run_id,summary,status="completed",reason="exploration_complete"):
    if status not in {"completed","partial","blocked","interrupted"}: raise ValueError("无效结束状态")
    if reason=='coverage_sufficient':reason='exploration_complete'
    def action(data):
        run=next((r for r in data["runs"] if r["id"]==run_id),None)
        if not run: raise ValueError("轮次不存在")
        report=coverage(run)
        if status=='completed' and run.get('scenario')=='opportunity_discovery':
            p=project(data,run['project_id'])
            pending=[i['title'] for i in data['items'] if i['project_id']==p['id'] and not i.get('discovery_disabled')
                     and (r:=rank_candidate(i,p,data.get('material_packs',[]),now()))['status']!='excluded' and r['total'] is None]
            if pending:raise ValueError('请先评估候选机会的探索要求和价值评分：'+'；'.join(pending))
        if status=='completed' and run.get('auto_verify'):
            pending=[i['title'] for i in data['items'] if i['id'] in {t['id'] for t in verification_tasks(data,run['project_id'])}
                     and (not i.get('verification_attempt') or i['verification_attempt'].get('profile_digest')!=profile_digest(project(data,run['project_id']))
                          or datetime.now(TZ)-datetime.fromisoformat(i['verification_attempt']['at'])>timedelta(days=7))]
            if pending:raise ValueError('请先逐个查证候选并登记核验结果（受阻也需记录实际入口）：'+'；'.join(pending))
        if status=="completed" and run.get("scenario")=="weekly_planning":
            valid_plan=next((p for p in reversed(data["weekly_plans"]) if run_id in p["run_ids"] and p["project_id"]==run["project_id"]
                             and p["profile_digest"]==profile_digest(project(data,run["project_id"])) and p["week_start"]==next_week()),None)
            if not valid_plan: raise ValueError("场景B需先保存下周行动卡；无值得新增投入的任务也要保存判断和依据")
        if reason not in {'exploration_complete','access_blocked','user_stopped','low_yield','budget_reached'}:
            raise ValueError('无效停止原因；本轮仅限制最大搜索次数，不设时间或阅读数量限制')
        if status!='completed' and reason=='exploration_complete':
            raise ValueError('提前结束请说明access_blocked/user_stopped/low_yield/budget_reached')
        if reason=="budget_reached" and run['counts']['searches']<run['limits']['searches']:
            raise ValueError("尚未达到最大搜索次数，不能标记为搜索预算耗尽")
        run.update({"status":status,"stage":"done","finished_at":now(),"summary":summary,"stop_reason":reason,"coverage":report})
        for request in data["requests"]:
            if request["id"]==run.get("request_id"): request["status"]=status
        event(data,run_id,"done",summary)
        return run
    return files.change(action)


def set_review(files,item_id,status,note=""):
    if status not in {"new","saved","skipped"} or len(note)>2000: raise ValueError("无效人工标记或备注过长")
    def action(data):
        item=next((i for i in data["items"] if i["id"]==item_id),None)
        if not item: raise ValueError("候选不存在")
        item["review"]={"status":status,"note":note,"at":now()}
        event(data,None,"review","人工标记："+item["title"]+" → "+status,item["url"],item_id)
        return item["review"]
    return files.change(action)


def add_source(files,payload):
    def action(data):
        remember_links(data,payload,data['active_project_id'],now(),'source')
        u=canonical(payload["url"])
        if any(s["url"]==u and s["project_id"]==data["active_project_id"] for s in data["sources"]): raise ValueError("该来源已在本项目观察清单中")
        if payload.get("role") not in {"peer","organizer","information"}: raise ValueError("请选择来源角色")
        if not payload.get("name","").strip() or not payload.get("reason","").strip(): raise ValueError("需填写名称和关注原因")
        row={"id":uuid4().hex[:10],"url":u,"name":payload["name"][:150],"role":payload["role"],
             "project_id":data["active_project_id"],"platform":detect_platform(u),
             "reason":payload["reason"][:1000],"similarity_note":payload.get("similarity_note") or "发展阶段与规模尚未确认",
             "added_at":now(),"last_checked_at":None,"seen_posts":[],"new_posts_last_check":[]}
        data["sources"].append(row)
        event(data,None,"source","加入内部观察清单："+row["name"],u)
        return row
    return files.change(action)


def _register_asset(data,p,metadata,title=None):
    old=next((a for a in p['asset_references'] if a['locator']==metadata['locator']),None)
    title=str(title or Path(metadata['locator']).stem)[:200]
    asset={**metadata,'id':old['id'] if old else uuid4().hex[:10],'title':title,'indexed_at':now()}
    if old:old.update(asset)
    else:p['asset_references'].append(asset)
    brief=title+'（本机素材；'+str(asset['specs'].get('duration_seconds','未知'))+'秒）'
    if brief not in p['assets_brief']:p['assets_brief']+='\n'+brief
    p['updated_at']=now()
    event(data,None,'asset','登记本地素材：'+title+'；权属与发布历史未确认')
    # Explicit project binding also works when the user registers into another project.
    data['events'][-1]['project_id']=p['id']
    return asset


def add_asset(files,payload):
    metadata=inspect_mp4(payload['path'])
    return files.change(lambda data:_register_asset(data,project(data,payload.get('project_id')),metadata,payload.get('title')))


def add_assets(files,payload):
    paths=payload.get('paths',[])
    if not isinstance(paths,list) or not 1<=len(paths)<=30 or not all(isinstance(p,str) for p in paths):raise ValueError('请选择1至30份素材')
    metadata=[inspect_mp4(path) for path in dict.fromkeys(paths)]
    def change(data):
        p=project(data,payload.get('project_id'))
        return {'assets':[_register_asset(data,p,m,payload.get('title') if len(metadata)==1 else None) for m in metadata]}
    return files.change(change)


def record_verification(files,payload):
    def action(data):
        p=project(data)
        remember_links(data,payload,p['id'],now(),'verification')
        item=next((i for i in data['items'] if i['id']==payload.get('id') and i['project_id']==p['id']),None)
        if not item:raise ValueError('机会不存在或不属于当前项目')
        if payload.get('profile_digest')!=profile_digest(p):raise ValueError('团队或素材资料已变化，请重新核验')
        attempt=payload.get('attempt',{})
        if not attempt.get('note') or not attempt.get('urls'):raise ValueError('需记录实际查证入口和结论')
        urls=[canonical(u) for u in attempt['urls']]
        update=copy.deepcopy(item)
        docs={d['id']:d for d in item.get('official_sources',[])}
        for d in payload.get('official_sources',[]):docs[d['id']]=d
        update['official_sources']=list(docs.values())
        update['facts']={**update.get('facts',{}),**payload.get('facts',{})}
        if 'participation' in payload:update['participation']=payload['participation']
        if 'open_questions' in payload:update['open_questions']=payload['open_questions']
        validate_item(update)
        if update.get('participation',{}).get('profile_digest') not in {None,profile_digest(p)}:raise ValueError('适配判断属于旧项目资料')
        item.update(update)
        item['verification_attempt']={'at':now(),'note':str(attempt['note'])[:5000],'urls':urls,'blocked':bool(attempt.get('blocked')),'profile_digest':profile_digest(p)}
        item['updated_at']=now()
        event(data,None,'verify',item['title']+'：'+attempt['note'],urls[0],item['id'])
        return item
    return files.change(action)


def public_state(files,workspace='exploration',pid=None):
    raw=files.load();p=workspace_project(raw,workspace,pid)
    empty_id='__empty_publishing__'
    if not p:
        p={'id':empty_id,'workspace':'publishing','name':'创建你的发布项目','direction':'','assets_brief':'',
           'resources_brief':'','team_profile':{},'asset_references':[],'discovery_platforms':['xiaohongshu','douyin']}
        raw['projects'].append(p)
    data=scoped(raw,p['id'])
    data['workspace']=workspace
    data['discovery_platform_catalog']=discovery_catalog()
    data['material_understanding']=None
    from material_media import video_compression_enabled
    data['llm']={'configured':bool(os.environ.get('RELAY_API_KEY')),'model':MATERIAL_MODEL,'compress_videos':video_compression_enabled(),
                 'material_timeout_seconds':request_timeout_seconds()}
    if p.get('materials'):
        service=MaterialService(files.path.parent/'materials.json')
        try:data['material_understanding']=service.status(p['materials']['analysis_id'])
        except (ValueError,OSError):pass
        finally:service.close()
    visit_urls=url_map(data,data['active_project_id'])
    refresh_checks(data,now())
    data['verification_tasks']=verification_tasks(data)
    annotate_deleted(data)
    data["lead_library"]=library(data)
    data["deleted_leads"]=library(data,deleted=True)
    data["lead_kinds"]=LEAD_KINDS
    data["frontier"]=[r for r in data["lead_library"] if r["status"] in {"new","watching","observed"}]
    data['selection_policy']=SELECTION_POLICY
    service=MaterialService(files.path.parent/'materials.json')
    try:data['material_packs']=view_packs(raw,service.load())
    finally:service.close()
    data['score_weights']={k:{'label':v[0],'weight':v[1]} for k,v in RANK_DIMENSIONS.items()}
    p=data["current_project"]
    for item in data["items"]:
        item["evidence_state"]=evidence_state(item)
        item["unknowns"]=unknowns(item)
        item["bucket"],item["qualification_issues"]=classify(item,p)
        item['related_links']=opportunity_links(item,lambda u:resolve_url(u,visit_urls))
        item['ranking']=rank_candidate(item,p,data['material_packs'],now())
        if workspace=='exploration':item['qualification_issues']=item['ranking']['issues']
    data['candidate_opportunities']=sorted([i for i in data['items'] if i['ranking']['status']!='excluded' and not i.get('discovery_disabled')],
        key=lambda i:(i['ranking']['total'] is None,-(i['ranking']['total'] or 0),i['id']))
    data['excluded_candidates']=[i for i in data['items'] if i['ranking']['status']=='excluded']
    data["results"]=[i for i in data["items"] if i["bucket"]=="result"]
    data["leads"]=[i for i in data["items"] if i["bucket"]=="lead"]
    data['pending_opportunities']=[i for i in data['leads'] if not i.get('discovery_disabled')]
    data["archive_items"]=[i for i in data["items"] if i["bucket"] in {"excluded","history"}]
    for run in data["runs"]:run["coverage"]=coverage(run)
    for signal in data["signals"]:signal["evidence_state"]=signal_state(signal)
    for asset in data["assets"]:asset["file_available"]=local_available(asset)
    data["weekly_plan"]=plan_view(data)
    data["publications"]=[view_job(data,j) for j in reversed(data["publication_jobs"])]
    data["platform_catalog"]=catalog(data,list(PLATFORMS.values()))
    if data["weekly_plan"]:
        for a in data["weekly_plan"]["actions"]:
            linked=next((j for j in data["publications"] if (j.get("source_action") or {}).get("action_id")==a["id"] and j["platform"]==platform(a.get("package",{}).get("platform","xiaohongshu"))["id"]),None) if a["kind"]=="content" else None
            if linked:
                a["publication_id"]=linked["id"]
                a["preparation"]=linked["preparation"]+"；"+linked["status_label"]
    data["next_week_start"]=next_week()
    data["stats"]={"items":len(data["items"]),"official":sum(bool(i.get("official_sources")) for i in data["items"]),
                   "results":len(data["results"]),"leads":len(data["leads"]),"opportunities":len(data['results'])+len(data['pending_opportunities']),"library_leads":len(data["lead_library"]),"archived":len(data["archive_items"]),"signals":len(data["signals"]),"publications":len(data["publications"]),
                   "peers":sum(s["role"]=="peer" for s in data["sources"]),
                   "followups":len(data["frontier"])}
    data["team_gaps"]=[name for key,name in [("applicant_type","报名主体"),("country","团队地区")]
                       if data["team"].get(key) is None]
    annotate_links(data,data['active_project_id'])
    if workspace=='exploration':data['stats']['opportunities']=len(data['candidate_opportunities'])
    data['projects']=[p for p in data['projects'] if p.get('workspace','exploration')==workspace and p['id']!=empty_id]
    return data


def _task_state(data,request_id):
    request=next((r for r in data['requests'] if r['id']==request_id),None)
    if not request:raise ValueError('探索任务不存在：'+request_id+'；请核对任务ID和当前项目目录')
    p=workspace_project(data,'exploration',request['project_id'])
    run=next((r for r in reversed(data['runs']) if r.get('request_id')==request_id),None)
    other=next((r for r in data['runs'] if r['status']=='running' and (not run or r['id']!=run['id'])),None)
    if run and run['status']=='running':action='resume'
    elif run or request['status'] in {'completed','partial','blocked','interrupted'}:action='report'
    elif request['status']=='waiting_codex':action='start'
    else:raise ValueError('任务状态与探索轮次不一致，请检查记录：'+request_id)
    return request,p,run,other,('conflict' if other and action in {'start','resume'} else action)


def task_context(files,request_id,begin=False):
    """Resolve one task without repository archaeology or unrelated project context."""
    data=files.load();request,p,run,other,action=_task_state(data,request_id)
    if begin and action=='conflict':
        raise ValueError('另一轮探索尚未结束：'+other['id']+'（项目 '+other['project_id']+'）；未启动或结束任何任务')
    if begin and action=='start':start_run(files,request_id=request_id)
    elif begin and action=='resume' and data['active_project_id']!=p['id']:
        def activate(current):
            _,target,_,_,current_action=_task_state(current,request_id)
            if current_action!='resume':raise ValueError('任务状态已变化，请重新读取任务')
            current['active_project_id']=target['id']
        files.change(activate)
    data=files.load();request,p,run,other,action=_task_state(data,request_id)
    state=public_state(files,'exploration',p['id'])
    if run:run={**copy.deepcopy(run),'coverage':coverage(run)}
    return {'request':{k:request.get(k) for k in ('id','status','mode','created_at','platforms','auto_verify','max_searches')},
            'project':{k:p.get(k) for k in ('id','name','exploration_requirements','seed_keywords','discovery_platforms','team_profile','max_searches')},
            'profile_digest':profile_digest(p),'run':run,'next_action':action,
            'conflicting_run':{k:other[k] for k in ('id','project_id','status')} if action=='conflict' else None,
            'context_command':'python demo.py status --project-id '+p['id'],
            'history':{'candidate_opportunities':len(state['candidate_opportunities']),'sources':len(state['sources']),
                       'leads':len(state['lead_library']),'deleted_leads':len(state['deleted_leads'])}}


def make_server(files,port,material_client_factory=None):
    csrf=secrets.token_urlsafe(24)
    materials=MaterialService(files.path.parent/'materials.json',material_client_factory)
    feed=homefeed.FeedFiles(files.path.parent/'homepage.json')
    def feed_start(payload):
        body=copy.deepcopy(payload)
        if body.get('login_confirmed') is not True:raise ValueError('请先登录小红书账号')
        current=feed.load()
        mode=body.get('mode') or ('continue' if current.get('active_project_id') else 'new')
        if mode not in {'new','continue'}:raise ValueError('请选择新建项目或继续旧项目')
        previous=homefeed.project_for(current,body.get('project_id')) if mode=='continue' else None
        homefeed.text(body.get('name',''),'项目名称',150,False)
        homefeed.text(body.get('preferences',''),'偏好方向',10000,False)
        if 'weights' in body:homefeed.score_weights(body['weights'])
        packs=files.load().get('material_packs',[])
        if 'material_pack_ids' in body:homefeed.material_ids(body['material_pack_ids'],packs)
        if body.get('material_directory') or body.get('material_analysis_id'):
            pack=add_pack(files,{**body,'name':''},materials,now())
            body['material_pack_ids']=[*body.get('material_pack_ids',previous.get('material_pack_ids',[]) if previous else []),pack['id']]
            packs=files.load().get('material_packs',[])
        return homefeed.create_session(feed,body,packs)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,status,body,content_type="application/json; charset=utf-8",extra_headers=None):
            raw=body if isinstance(body,bytes) else body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            headers={"Content-Security-Policy":"default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'",**(extra_headers or {})}
            for key,value in headers.items():self.send_header(key,value)
            self.end_headers()
            self.wfile.write(raw)
        def json(self,status,data): self.send(status,json.dumps(data,ensure_ascii=False))
        def valid_host(self):
            actual=self.headers.get("Host","")
            return actual in {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}
        def valid_page_origin(self):
            origin=self.headers.get('Origin')
            if origin:
                parsed=urlsplit(origin)
                allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
                if parsed.scheme!='http' or parsed.netloc not in allowed:return False
            return self.headers.get('Sec-Fetch-Site','same-origin') in {'same-origin','none'}
        def do_GET(self):
            if not self.valid_host(): return self.json(403,{"error":"仅允许本机访问"})
            route=urlsplit(self.path).path
            try:
                query=dict(parse_qsl(urlsplit(self.path).query))
                if route=='/api/homefeed/html':
                    try:
                        data=homefeed.notebook(feed.load(),[],query.get('project_id'))
                        stamp=homefeed.now();name=share_page.filename(data,stamp)
                        body=share_page.render(data,stamp)
                    except ValueError as error:return self.json(400,{'error':str(error)})
                    return self.send(200,body,'text/html; charset=utf-8',{
                        'Content-Disposition':"attachment; filename=\"candidate-opportunities.html\"; filename*=UTF-8''"+quote(name,safe=''),
                        'Content-Security-Policy':share_page.content_security_policy()+"; frame-ancestors 'none'"})
                if route in {'/api/homefeed','/api/homefeed/report','/api/homefeed/csv'}:
                    packs=files.load().get('material_packs',[])
                    raw_feed=feed.load()
                    data=homefeed.notebook(raw_feed,packs,query.get('project_id'))
                    if data['active_session']:data['execution_prompt']=homefeed.prompt(data['active_session']['id'])
                    if route.endswith('/report'):return self.send(200,homefeed.report(data),'text/markdown; charset=utf-8')
                    if route.endswith('/csv'):return self.send(200,'\ufeff'+homefeed.csv_text(data),'text/csv; charset=utf-8')
                    from material_media import video_compression_enabled
                    selected=homefeed.project_packs(raw_feed,packs,data['current_project']['id']) if data['current_project'] else []
                    data.update(csrf=csrf,material_packs=view_packs({'material_packs':selected},materials.load()),
                                llm={'configured':bool(os.environ.get('RELAY_API_KEY')),'model':MATERIAL_MODEL,
                                     'compress_videos':video_compression_enabled(),'material_timeout_seconds':request_timeout_seconds()})
                    return self.json(200,data)
                page_files=ProjectFiles(files,query.get('project_id')) if query.get('workspace')=='publishing' and route not in {'/api/state','/api/materials/status','/api/materials/catalog'} and route.startswith('/api/') else files
                if route=="/api/state":
                    data=public_state(files,query.get('workspace','exploration'),query.get('project_id'))
                    data["csrf"]=csrf
                    return self.json(200,data)
                if route=='/api/materials/status':return self.json(200,materials.status(query.get('id')))
                if route=='/api/materials/catalog':return self.json(200,materials.load())
                if route=='/favicon.ico':return self.send(204,b'','image/x-icon')
                if route=='/api/candidates.csv':
                    state=public_state(files,'exploration',query.get('project_id'));stream=io.StringIO(newline='');writer=csv.writer(stream)
                    writer.writerow(['项目','候选机会','优先级分','已知权重','状态','未确认事项','原始入口','评分依据'])
                    for i in state['candidate_opportunities']:
                        r=i['ranking'];writer.writerow([csv_cell(v) for v in [state['current_project']['name'],i['title'],r['total'],r['known_weight'],r['status'],'；'.join(r['issues']),i['url'],json.dumps(r['components'],ensure_ascii=False)]])
                    return self.send(200,'\ufeff'+stream.getvalue(),'text/csv; charset=utf-8')
                if route=="/api/export.csv":
                    selected=scoped(page_files.load())
                    bucket=dict(parse_qsl(urlsplit(self.path).query)).get("bucket")
                    if bucket:selected["items"]=[i for i in selected["items"] if classify(i,selected["current_project"])[0]==bucket]
                    return self.send(200,"\ufeff"+csv_text(selected),"text/csv; charset=utf-8")
                if route=="/api/export.json": return self.json(200,page_files.load())
                if route=="/api/publication-image":
                    query=dict(parse_qsl(urlsplit(self.path).query));job=job_for(page_files.load(),query.get("job_id"))
                    cover=next((c for c in job["covers"] if c["id"]==query.get("cover_id")),None)
                    if not cover:return self.json(404,{"error":"封面不存在"})
                    path=cover["frame_path"] if query.get("type")=="frame" else cover["path"]
                    return self.send(200,Path(path).read_bytes(),"image/png")
                if route=="/api/publication-package":
                    query=dict(parse_qsl(urlsplit(self.path).query));data=page_files.load();job=job_for(data,query.get("id"))
                    if query.get("format")=="md":return self.send(200,package_text(view_job(data,job)),"text/markdown; charset=utf-8")
                    try:stream=package_zip(data,job)
                    except ValueError as error:return self.json(400,{"error":str(error)})
                    with stream:
                        stream.seek(0,2);size=stream.tell();stream.seek(0)
                        self.send_response(200);self.send_header("Content-Type","application/zip")
                        self.send_header("Content-Disposition",'attachment; filename="publication-'+job["id"]+'-v'+str(job["revisions"][-1]["number"])+'.zip"')
                        self.send_header("Content-Length",str(size));self.send_header("Cache-Control","no-store");self.end_headers()
                        try:
                            while chunk:=stream.read(262144):self.wfile.write(chunk)
                        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
                    return
                if route=="/api/actions.csv":return self.send(200,"\ufeff"+planning_csv(scoped(page_files.load()),csv_cell),"text/csv; charset=utf-8")
                if route=="/api/leads.csv":
                    data=page_files.load()
                    return self.send(200,"\ufeff"+leads_csv(data,csv_cell,project(data)["id"]),"text/csv; charset=utf-8")
                if route=="/api/action-package":
                    query=dict(parse_qsl(urlsplit(self.path).query));data=scoped(page_files.load())
                    plan=next((p for p in data["weekly_plans"] if p["id"]==query.get("plan_id")),None)
                    if not plan:return self.json(404,{"error":"计划不存在"})
                    data["weekly_plans"]=[plan];view=plan_view(data)
                    action=next((a for a in view["actions"] if a["id"]==query.get("action_id")),None)
                    if not action:return self.json(404,{"error":"行动不存在"})
                    return self.send(200,package_markdown(view,action),"text/markdown; charset=utf-8")
                if route.startswith("/api/media/"):
                    if query.get('library_pack'):
                        pack=next((p for p in files.load().get('material_packs',[]) if p['id']==query['library_pack'] and not p.get('deleted')),None)
                        collection=pack.get('assets',[]) if pack else []
                    else:collection=scoped(page_files.load())["assets"]
                    asset=next((a for a in collection if a["id"]==route.removeprefix("/api/media/")),None)
                    if not asset or not local_available(asset):return self.json(404,{"error":"素材未登记或版本已变化"})
                    path=Path(asset["locator"]);size=path.stat().st_size;start=0;end=size-1
                    requested=self.headers.get("Range")
                    if requested:
                        match=re.fullmatch(r"bytes=(\d+)-(\d*)",requested)
                        if not match:return self.json(416,{"error":"不支持此读取范围"})
                        start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
                        if not 0<=start<=end<size:return self.json(416,{"error":"读取范围无效"})
                    self.send_response(206 if requested else 200)
                    self.send_header("Content-Type",asset.get("mime","video/mp4"));self.send_header("Accept-Ranges","bytes")
                    self.send_header("Content-Length",str(end-start+1));self.send_header("Cache-Control","no-store")
                    self.send_header("X-Content-Type-Options","nosniff")
                    if requested:self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    with path.open("rb") as stream:
                        stream.seek(start);remaining=end-start+1
                        try:
                            while remaining:
                                chunk=stream.read(min(262144,remaining))
                                if not chunk:break
                                self.wfile.write(chunk);remaining-=len(chunk)
                        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
                    return
                assets={"/":("home.html","text/html; charset=utf-8"),"/explore":("index.html","text/html; charset=utf-8"),"/publish":("publish.html","text/html; charset=utf-8"),"/app.js":("app.js","text/javascript; charset=utf-8"),"/styles.css":("styles.css","text/css; charset=utf-8"),"/actions.css":("actions.css","text/css; charset=utf-8"),"/publishing.js":("publishing.js","text/javascript; charset=utf-8"),"/publishing.css":("publishing.css","text/css; charset=utf-8"),"/materials.js":("materials.js","text/javascript; charset=utf-8"),"/directory-picker.css":("directory-picker.css","text/css; charset=utf-8")}
                assets['/discovery.js']=('discovery.js','text/javascript; charset=utf-8')
                assets['/']=assets['/explore']=('feed.html','text/html; charset=utf-8')
                assets['/homefeed.js']=('homefeed.js','text/javascript; charset=utf-8')
                assets['/homefeed.css']=('homefeed.css','text/css; charset=utf-8')
                if route in assets:
                    name,mime=assets[route]
                    return self.send(200,(ROOT/"ui"/name).read_bytes(),mime)
                return self.json(404,{"error":"页面不存在"})
            except (ValueError,OSError) as error: return self.json(500,{"error":str(error)})
        def do_POST(self):
            if not self.valid_host() or self.headers.get("X-Demo-Token")!=csrf:
                return self.json(403,{"error":"请从本机界面操作"})
            try:
                length=int(self.headers.get("Content-Length","0"))
                if length>20000: return self.json(413,{"error":"内容过长"})
                payload=json.loads(self.rfile.read(length))
                route=urlsplit(self.path).path
                if route=='/api/homefeed/start':return self.json(200,feed_start(payload))
                if route=='/api/homefeed/project/select':return self.json(200,homefeed.select_project(feed,payload.get('id')))
                if route=='/api/homefeed/library/add':
                    target=homefeed.project_for(feed.load(),payload.get('project_id'))
                    pack=add_pack(files,payload,materials,now())
                    homefeed.attach_pack(feed,target['id'],pack['id'],files.load().get('material_packs',[]))
                    return self.json(200,pack)
                if route=='/api/homefeed/library/delete':return self.json(200,homefeed.detach_pack(feed,payload.get('project_id'),payload.get('id')))
                if route=='/api/homefeed/stop':return self.json(200,homefeed.stop_session(feed,payload.get('id')))
                if route=='/api/homefeed/record':return self.json(200,homefeed.record(feed,payload))
                operation_files=ProjectFiles(files,payload.get('project_id')) if payload.get('workspace')=='publishing' and route not in {'/api/project/select','/api/publishing/projects'} and not route.startswith('/api/materials/') else files
                if route=='/api/materials/browse':
                    if not self.valid_page_origin():return self.json(403,{'error':'仅允许当前本机页面浏览目录'})
                    return self.json(200,browse_directories(payload.get('directory'),ROOT.parent))
                if route=='/api/materials/pick':return self.json(200,{'directory':pick_directory()})
                if route=='/api/materials/analyze':return self.json(200,materials.start(payload.get('directory'),retry=payload.get('retry') is True))
                if route=='/api/publishing/projects':return self.json(200,create_publishing_project(files,payload,materials))
                if route=='/api/exploration/requests':return self.json(200,request_run(files,payload))
                if route=='/api/library/add':return self.json(200,add_pack(files,payload,materials,now()))
                if route=='/api/library/delete':return self.json(200,delete_pack(files,payload.get('id'),now()))
                if route=='/api/assessments':return self.json(200,save_assessment(files,payload,now()))
                if route=="/api/requests": result=request_run(files,payload)
                elif route=="/api/project/select": result=select_project(files,payload["project_id"],payload.get('workspace','exploration'))
                elif route=="/api/review": result=set_review(operation_files,payload["id"],payload["status"],payload.get("note",""))
                elif route=="/api/sources": result=add_source(operation_files,payload)
                elif route=="/api/leads": result=add_lead(operation_files,payload,now())
                elif route=="/api/leads/delete": result=remove_lead(operation_files,payload,now())
                elif route=="/api/leads/restore": result=remove_lead(operation_files,payload,now(),restore=True)
                elif route=="/api/assets": result=add_asset(operation_files,payload)
                elif route=='/api/assets/batch':result=add_assets(operation_files,payload)
                elif route=='/api/assets/pick':
                    paths=pick_files()
                    if len(paths)>30:raise ValueError('每次最多选择30份素材')
                    selected=[]
                    for value in paths:
                        path=Path(value).resolve(strict=True)
                        if not path.is_file() or path.suffix.lower()!='.mp4':raise ValueError('当前支持MP4素材')
                        selected.append({'path':str(path),'name':path.name})
                    result={'files':selected}
                elif route=="/api/research":result=record_snapshot(operation_files,payload,now())
                elif route=="/api/action-review": result=review_action(operation_files,payload,now())
                elif route=="/api/publications":result=create_job(operation_files,payload,now())
                elif route=="/api/publications/edit":result=edit_job(operation_files,payload,now())
                elif route=="/api/publications/cover":result=generate_cover(operation_files,payload,now())
                elif route=="/api/publications/approve":result=approve_job(operation_files,payload,now())
                elif route=="/api/publications/request-draft":result=request_draft(operation_files,payload,now())
                elif route=="/api/publications/receipt":
                    if payload.get("kind") not in {"published_reported","unknown"}:raise ValueError("平台草稿完成只能由实际操作后的CLI回执登记")
                    result=record_execution(operation_files,payload,now())
                else: return self.json(404,{"error":"接口不存在"})
                return self.json(200,result)
            except (ValueError,OSError,KeyError,TypeError) as error: return self.json(400,{"error":str(error)})
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    close=server.server_close
    def close_services():
        materials.close();close()
    server.server_close=close_services
    return server


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description="多平台创作探索 · 文件版 demo")
    parser.add_argument("--data",default=str(STATE_PATH))
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("init")
    status_parser=sub.add_parser("status")
    status_parser.add_argument("--workspace",choices=["exploration","publishing"],default="exploration")
    status_parser.add_argument("--project-id")
    task=sub.add_parser('task',help='按任务ID读取执行上下文；--begin启动或恢复同一轮次，不执行联网搜索')
    task.add_argument('request_id')
    task.add_argument('--begin',action='store_true',help='准备执行：启动待处理任务，或切回正在执行的任务项目')
    sub.add_parser("export")
    lead=sub.add_parser('lead',help='AI线索工具：列出候选、自主补充与调整、可逆剪枝；不自动选择下一条')
    lead.add_argument('action',choices=['list','seed','add','update','delete','restore'])
    lead.add_argument('--file',help='写操作的JSON参数；update/delete/restore需decision说明取舍理由')
    research=sub.add_parser("research",help="保存真实平台检查或观察样本，不触发后台搜索")
    research.add_argument("action",choices=["check","snapshot"])
    research.add_argument("file")
    request=sub.add_parser("request")
    request.add_argument("--file",help="探索要求与种子词JSON，mode为new或continue；无需素材")
    start=sub.add_parser("start")
    start.add_argument("--project-id")
    start.add_argument("--request-id")
    ingest=sub.add_parser("record")
    ingest.add_argument("file")
    verifier=sub.add_parser('verify',help='列出全部待核验机会，或保存Agent实际查证的证据并自动比对团队/素材')
    verifier.add_argument('--file')
    assessor=sub.add_parser('assess',help='保存基于官方证据的探索要求判断、权益评分与素材匹配')
    assessor.add_argument('--file',required=True)
    link_repair=sub.add_parser('links',help='保存实际页面完整链接，更新访问参数；不会新增机会或篡改笔记ID')
    link_repair.add_argument('--file',required=True)
    planner=sub.add_parser("plan",help="保存经过判断的每周行动卡JSON，不调用外部API")
    planner.add_argument("file")
    publisher=sub.add_parser("publication",help="场景A发布包：本地准备、文案、封面与实际执行回执")
    publisher.add_argument("--project-id",help="发布页面项目ID；操作该项目而不切换探索项目")
    publisher.add_argument("action",choices=["create","edit","cover","execution"])
    publisher.add_argument("file",help="本次操作的JSON；不支持由CLI伪造用户确认")
    asset=sub.add_parser("asset",help="登记创作者提供的本地MP4；不搬运文件")
    asset.add_argument("--file",required=True)
    asset.add_argument("--title")
    asset.add_argument("--project-id")
    done=sub.add_parser("finish")
    done.add_argument("run_id")
    done.add_argument("--summary",required=True)
    done.add_argument("--status",choices=["completed","partial","blocked","interrupted"],default="completed")
    done.add_argument("--reason",default="exploration_complete")
    serve=sub.add_parser("serve")
    serve.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    files=Files(args.data)
    try:
        if args.command=='publication' and args.project_id:files=ProjectFiles(files,args.project_id)
        if args.command=="init": result=files.change(lambda data:{"path":str(files.path),"items":len(data["items"])})
        elif args.command=="status":
            state=public_state(files,args.workspace,args.project_id)
            result={"stats":state["stats"],"requests":state["requests"],"latest_run":state["runs"][-1] if state["runs"] else None,
                    "current_project":state["current_project"],"profile_digest":profile_digest(state["current_project"]),
                    "pending_followups":[f for f in state["followups"] if f["status"]=="new" and not f["discovery_disabled"]],"sources":state["sources"],
                    "frontier":state["frontier"],"lead_library":state["lead_library"],"deleted_leads":state["deleted_leads"],
                    "signals":state["signals"],"assets":state["assets"],"weekly_plan":state["weekly_plan"],"next_week_start":state["next_week_start"],
                    "publications":state["publications"],"workspace":state["workspace"],"material_understanding":state["material_understanding"],
                    "candidate_opportunities":state['candidate_opportunities'],"excluded_candidates":state['excluded_candidates'],
                    "material_packs":state['material_packs'],"score_weights":state['score_weights']}
        elif args.command=='task':result=task_context(files,args.request_id,args.begin)
        elif args.command=="request": result=request_run(files,read(args.file) if args.file else {"mode":"continue"})
        elif args.command=='lead':
            if args.action=='list':
                state=public_state(files)
                result={k:state[k] for k in ['selection_policy','frontier','lead_library','deleted_leads']}
            elif args.action=='seed':result=files.change(lambda data:seed_initial(data,now()))
            else:
                if not args.file:raise ValueError('线索写操作需要--file JSON文件')
                payload=read(args.file)
                if args.action=='add':result=add_lead(files,payload,now(),actor='agent')
                elif args.action=='update':result=update_lead(files,payload,now(),actor='agent')
                else:result=remove_lead(files,payload,now(),restore=args.action=='restore',actor='agent')
        elif args.command=="start": result=start_run(files,request_id=args.request_id,project_id=args.project_id)
        elif args.command=="research":result={"check":record_check,"snapshot":record_snapshot}[args.action](files,read(args.file),now())
        elif args.command=="record": result=record(files,read(args.file))
        elif args.command=='verify':
            result=record_verification(files,read(args.file)) if args.file else files.change(lambda data:{'tasks':verification_tasks(data),'team':project(data).get('team_profile',{})})
        elif args.command=='links':result=save_links(files,read(args.file),now())
        elif args.command=='assess':result=save_assessment(files,read(args.file),now())
        elif args.command=="plan": result=save_plan(files,read(args.file),now())
        elif args.command=="publication":result={"create":create_job,"edit":edit_job,"cover":generate_cover,"execution":record_execution}[args.action](files,read(args.file),now())
        elif args.command=="asset": result=add_asset(files,{"path":args.file,"title":args.title,"project_id":args.project_id})
        elif args.command=="finish": result=finish(files,args.run_id,args.summary,args.status,args.reason)
        elif args.command=="export":
            files.export()
            result={"directory":str(files.path.parent)}
        else:
            server=make_server(files,args.port)
            print(f"Local: http://127.0.0.1:{server.server_port}",flush=True)
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()
            return 0
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps({"error":str(error)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
