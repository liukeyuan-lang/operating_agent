"""Small project/coverage/result rules; no scheduler or external services."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from platforms import detect_platform

TZ=timezone(timedelta(hours=8))
PLAN={"targets":{},"limits":{"searches":50}}
COUNTERS=('searches','post_reads','source_checks','official_reads')
GATES=("eligibility","asset_fit","rights_clearance","resource_fit")
REQUIRED=("eligibility","ai_policy","deadline","attendance","fees","formats","rights","entry_url","open_status")
LABELS={"eligibility":"报名资格","ai_policy":"AI作品政策","deadline":"截止时间","attendance":"到场要求",
        "fees":"费用","formats":"作品规格","rights":"首发与授权","entry_url":"报名入口","open_status":"当前开放状态",
        "asset_fit":"素材适配","rights_clearance":"作品权属","resource_fit":"时间、预算与到场可行性"}


def instant(value):
    result=datetime.fromisoformat(value.replace("Z","+00:00"))
    if result.tzinfo is None: raise ValueError("时间必须包含时区")
    return result


def search_limit(value):
    if isinstance(value,str) and value.isascii() and value.isdigit():value=int(value)
    if type(value) is not int or value<1:raise ValueError('最多搜索次数须为正整数')
    return value


def migrate(data):
    if data.get("schema_version") not in {2,3}: raise ValueError("数据版本不匹配")
    pid=data["project"].get("id","default-project")
    if not data.get("projects"):
        assets="\n".join(a.get("title",a.get("id",""))+"："+a.get("locator","")+"（"+a.get("availability","未知")+"）" for a in data.get("assets",[]))
        data["projects"]=[{"id":pid,"name":data["project"]["name"],"direction":data["project"].get("description",""),
                           "assets_brief":assets,"resources_brief":"团队地区、报名主体和可投入工时仍待确认。",
                           "created_at":data.get("updated_at"),"updated_at":data.get("updated_at")}]
    default=data["projects"][0]["id"]
    for p in data["projects"]:
        p.setdefault('workspace','exploration')
        if p['workspace']=='exploration':p.setdefault('max_searches',PLAN['limits']['searches'])
        p.setdefault("discovery_platforms",["xiaohongshu"])
        p.setdefault("asset_references",copy.deepcopy(data.get("assets",[])) if p["id"]==default else [])
        p.setdefault("team_profile",copy.deepcopy(data.get("team",{})) if p["id"]==default else {})
    data.setdefault("active_project_id",default)
    data.setdefault('active_publishing_project_id',None)
    for collection in ("items","sources","followups","runs","requests","events","signals","weekly_plans","publication_jobs","platform_checks","research_snapshots","lead_deletions","access_links"):
        data.setdefault(collection,[])
        for row in data[collection]:
            row.setdefault("project_id",default)
            if collection in {"items","sources"}:row.setdefault("platform",detect_platform(row.get("url","")))
            if collection=="followups":row.setdefault("platform",detect_platform(row.get("parent_url") or row.get("target","")))
            if collection=="signals":row.setdefault("platform",next((detect_platform(e.get("url","")) for e in row.get("evidence",[]) if detect_platform(e.get("url",""))!="web"),"web"))
            if collection in {"runs","requests"}:row.setdefault("platforms",["xiaohongshu"])
            if collection=="runs" and "profile_digest" not in row: row["legacy_demo"]=True
            if collection=='runs':
                row['targets']={}
                row['limits']={'searches':search_limit(row.get('limits',{}).get('searches',PLAN['limits']['searches']))}
                row.pop('max_minutes',None)
                row.pop('coverage_directions',None)
                for key in COUNTERS:row.setdefault('counts',{}).setdefault(key,0)
            if collection=='requests':
                linked=next((r for r in reversed(data['runs']) if r.get('request_id')==row['id']),None)
                owner=next((p for p in data['projects'] if p['id']==row['project_id']),{})
                row.setdefault('max_searches',linked['limits']['searches'] if linked else owner.get('max_searches',PLAN['limits']['searches']))
    data["schema_version"]=3
    from discovery import migrate_discovery
    migrate_discovery(data)
    return data


def project(data,pid=None):
    pid=pid or data["active_project_id"]
    row=next((p for p in data["projects"] if p["id"]==pid),None)
    if row is None: raise ValueError("探索项目不存在")
    return row


def profile_digest(profile):
    fields={k:profile.get(k,"") for k in ("id","direction","assets_brief","resources_brief","team_profile","asset_references")}
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def scoped(data,pid=None):
    p=project(data,pid)
    result=copy.deepcopy(data)
    result['active_project_id']=p['id']
    result["current_project"]=copy.deepcopy(p)
    result["project"]={**data["project"],"id":p["id"],"name":p["name"],"description":p["direction"]}
    result["assets"]=copy.deepcopy(p.get("asset_references",[]))
    result["team"]=copy.deepcopy(p.get("team_profile",{}))
    for key in ("items","sources","followups","runs","requests","events","signals","weekly_plans","publication_jobs","platform_checks","research_snapshots","lead_deletions","access_links"):
        result[key]=[r for r in result[key] if r["project_id"]==p["id"]]
    return result


def classify(item,profile,at=None):
    current=instant(at) if at else datetime.now(TZ)
    facts=item.get("facts",{})
    due=facts.get("deadline",{}).get("at")
    invalid_due=False
    if due:
        try:
            if instant(due)<=current: return "excluded",["已截止"]
        except ValueError: invalid_due=True
    if item.get("excluded_reason"): return "excluded",[item["excluded_reason"]]
    if facts.get("open_status",{}).get("value")=="closed": return "excluded",["官方已关闭征集"]
    if facts.get("ai_policy",{}).get("allowed") is False: return "excluded",["不接受此类AI作品"]
    participation=item.get("participation",{})
    if any(participation.get(g,{}).get("status")=="fail" for g in GATES):
        return "excluded",[participation[g].get("reason",g+"不符合") for g in GATES if participation.get(g,{}).get("status")=="fail"]
    if item.get("historical"): return "history",["既往参展/参赛记录，不是当前开放机会"]
    issues=[]
    if invalid_due: issues.append("截止时刻格式无效")
    docs={d["id"]:d for d in item.get("official_sources",[])}
    for key in REQUIRED:
        f=facts.get(key,{})
        if f.get("status")!="confirmed": issues.append(LABELS[key]+"尚未核实")
        doc=docs.get(f.get("source_id"))
        if f.get("status")=="confirmed":
            if not doc or not f.get("evidence") or f["evidence"] not in doc.get("excerpt",""):
                issues.append(LABELS[key]+"缺少原始证据")
            elif current-instant(doc["read_at"])>timedelta(days=7): issues.append(LABELS[key]+"证据需要重新核验")
    if not due and not (facts.get("deadline",{}).get("kind")=="rolling" and facts["deadline"].get("status")=="confirmed"):
        issues.append("截止具体时刻和时区未核实")
    if facts.get("open_status",{}).get("value")!="open": issues.append("当前开放状态未确认")
    if facts.get("ai_policy",{}).get("allowed") is not True: issues.append("AI作品许可未明确")
    if participation.get("profile_digest")!=profile_digest(profile): issues.append("尚未针对当前项目资料完成适配核验")
    for gate in GATES:
        entry=participation.get(gate,{})
        if entry.get("status")!="pass" or not entry.get("reason"): issues.append(LABELS[gate]+"尚未确认")
    if not participation.get("checked_at"): issues.append("项目适配核验时间缺失")
    elif current-instant(participation["checked_at"])>timedelta(days=7): issues.append("项目适配核验已过期")
    if item.get("open_questions"): issues.extend(item["open_questions"])
    return ("lead",list(dict.fromkeys(issues))) if issues else ("result",[])


def coverage(run):
    achieved=dict(run["counts"])
    if not run.get("legacy_demo"):
        achieved["source_checks"]=min(run["counts"]["source_checks"],len(set(run.get("checked_source_urls",[]))))
        achieved["post_reads"]=min(run["counts"]["post_reads"],len(set(run.get("read_post_urls",[]))))
        achieved["searches"]=len({(q["channel"]," ".join(q["query"].casefold().split())) for q in run.get("search_queries",[])})
    if run.get("scenario")=="weekly_planning":
        achieved["focus_areas"]=len({q.get("focus") for q in run.get("search_queries",[]) if q.get("focus") in {"topics","peers","opportunities"}})
    if run.get('platforms'):
        from platforms import platform
        achieved["platforms"]=len({('web' if q['channel']=='web' else platform(q["channel"])["id"]) for q in run.get("search_queries",[])}&set(run["platforms"]))
    return {"sufficient":True,"gaps":{},"achieved":achieved,"targets":{}}
