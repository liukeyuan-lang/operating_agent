"""Scenario A: versioned local publication packages and honest handoff state."""
import copy
import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from platforms import platform,account_url,content_url

from media import local_available
from workflow import TZ,instant, project, scoped

METHOD={"name":"Creator Buddy 方法参考（项目适配）",
        "commit":"edf46c567ff54b72ee2157d06f3a02dbd67aaa9c",
        "modules":["space-xhs-buddy","space-xhs-title","space-xhs-writer"],
        "mode":"参考专项方法；未安装或执行上游总控/采集脚本，不代表平台已接通"}
CHECKS={"media":"已审看整片，字幕、音轨和画质可用", "rights":"本次使用的画面、音乐、字体等已获授权",
        "history":"已核对发布历史、首发和排他限制", "copy":"已核对标题、正文和封面与作品一致",
        "platform":"已核对当前平台要求、AI标识和目标账号"}
STATE_NAMES={"preparing":"准备中","needs_review":"待核对/确认","approved":"本版发布包已确认",
             "draft_requested":"草稿填写任务已保存","draft_filled":"平台草稿已核实",
             "blocked":"草稿填写受阻","status_unknown":"执行状态未知，需核查",
             "published_reported":"已发布 · 人工登记待回查"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def job_for(data, job_id):
    job=next((j for j in data["publication_jobs"] if j["id"]==job_id and j["project_id"]==data["active_project_id"]),None)
    if not job:raise ValueError("发布准备任务不存在或不属于当前项目")
    return job


def asset_for(data, job):
    return next((a for a in project(data,job["project_id"])["asset_references"] if a["id"]==job["asset_id"]),None)


def profile_url(value,selected="xiaohongshu"):
    return account_url(value,selected)


def cover_for(job, revision):
    return next((c for c in job["covers"] if c["id"]==revision.get("cover_id") and c["asset_version"]==job["asset_version"]),None)


def cover_available(cover):
    if not cover:return False
    try:return hashlib.sha256(Path(cover["path"]).read_bytes()).hexdigest()==cover["sha256"]
    except OSError:return False


def revision_hash(job, revision):
    cover=cover_for(job,revision)
    return fingerprint({"asset_version":job["asset_version"],"platform":job["platform"],
                        **{k:revision.get(k) for k in ("title","body","tags","account_name","account_url","scheduled_at")},
                        "cover_sha256":cover["sha256"] if cover else None})


def preflight(data, job):
    r=job["revisions"][-1];asset=asset_for(data,job);cover=cover_for(job,r)
    config=platform(job["platform"])
    rows=[]
    def check(key,label,status,note):rows.append({"key":key,"label":label,"status":status,"note":note})
    media_ok=bool(asset and local_available(asset,job["asset_version"]))
    check("media_file","素材文件与版本","pass" if media_ok else "blocked","原片可读取且与选定版本一致" if media_ok else "素材已移动、修改或未登记；请重新读取")
    title=r["title"].strip();body=r["body"].strip();combined=body+"\n"+" ".join(r["tags"])
    check("title","标题","pass" if title and len(title)<=config["title_budget"] else "blocked",f'{len(title)}/{config["title_budget"]} 字符工作阈值；最终以'+config["name"]+"编辑器为准")
    check("body","正文与标签","pass" if body and len(combined)<=config["body_budget"] else "blocked",f'{len(combined)}/{config["body_budget"]} 字符工作阈值（含标签）；不是已核实的平台上限')
    check("placeholders","成稿完整性","blocked" if any(s in title+body for s in ("[待填","[此处需","TODO","待补真实细节")) else "pass","不以待填占位符冒充成稿")
    check("cover","封面文件","pass" if cover_available(cover) else "blocked","PNG已生成且文件校验一致" if cover_available(cover) else "尚无选定的封面成图，或封面文件已变化")
    check("account","目标账号","pass" if r["account_name"].strip() and r["account_url"] else "blocked","账号已指定；实际登录身份仍须在平台核对" if r["account_url"] else "尚未指定本次发布的账号主页")
    evidence=job.get("platform_evidence")
    if evidence and datetime.now(TZ)-instant(evidence["read_at"])<=timedelta(days=7):
        specs=(asset or {}).get("specs",{});size=(asset or {}).get("file_signature",{}).get("size")
        fits=bool(size is not None and specs.get("duration_seconds") is not None and size<=evidence["max_video_bytes"] and specs["duration_seconds"]<=evidence["max_video_seconds"])
        check("upload_rules","已读的视频上传要求","pass" if fits else "blocked","原始上传面板："+evidence["excerpt"]+" 标题、封面与AI声明须在实际编辑器另核。")
    else:
        check("upload_rules","视频上传要求","warning","未记录新鲜的原始上传面板规则，需人工核对；不把第三方Skill里的平台断言当官方事实。")
    width=(asset or {}).get("specs",{}).get("width")
    if width and width<1080:check("quality","画质提醒","warning",f"原片宽度{width}px；封面排版不代表视频已变成高清，需审看片质")
    for key,label in CHECKS.items():
        checked=r.get("checks",{}).get(key) is True
        check("review_"+key,label,"pass" if checked else "pending","已由使用者勾选，本次内容版本有效" if checked else "尚待人工核对")
    previous=[j for j in data["publication_jobs"] if j["id"]!=job["id"] and j["platform"]==job["platform"] and j["project_id"]==job["project_id"] and j["asset_version"]==job["asset_version"]
              and any(e.get("url") for e in j.get("receipts",[])) and j["revisions"][-1].get("account_url")==r["account_url"]]
    if previous:check("duplicate","重复发布提醒","blocked","该账号已有同版素材的发布记录；先核查已有链接，不自动重复投递")
    uncertain=[j for j in data["publication_jobs"] if j["id"]!=job["id"] and j["platform"]==job["platform"] and j["project_id"]==job["project_id"] and j["asset_version"]==job["asset_version"]
               and j["revisions"][-1].get("account_url")==r["account_url"] and (j.get("draft",{}).get("status")=="unknown" or j.get("receipts") and not j["receipts"][-1].get("url"))]
    if uncertain:check("uncertain_previous","已有未知执行","blocked","同版素材在目标账号有状态未知的记录，先核查，不能重建发布包绕过")
    check("draft","平台草稿","pass" if job.get("draft",{}).get("status")=="filled" and job["draft"].get("revision_hash")==r["hash"] else "pending",
          "草稿仅在实际核查后登记；本地发布包不会自动变成平台草稿")
    return rows


def view_job(data, job):
    view=copy.deepcopy(job);r=view["revisions"][-1]
    view["platform_config"]=platform(job["platform"])
    view["current"]=r;view["checks_catalog"]=CHECKS;view["preflight"]=preflight(data,job)
    view["asset"]=copy.deepcopy(asset_for(data,job))
    if view["asset"]:view["asset"]["file_available"]=local_available(view["asset"],job["asset_version"])
    blockers=[x for x in view["preflight"] if x["status"]=="blocked"]
    pending=[x for x in view["preflight"] if x["status"]=="pending" and x["key"]!="draft"]
    approval=job.get("approval")
    valid=bool(approval and approval["revision_hash"]==r["hash"] and not blockers and not pending)
    status="preparing" if not r["body"] or not cover_available(cover_for(job,r)) else "needs_review"
    if valid:status="approved"
    if job.get("draft",{}).get("revision_hash")==r["hash"]:
        status={"requested":"draft_requested","filled":"draft_filled","blocked":"blocked","unknown":"status_unknown"}.get(job["draft"]["status"],status) if valid else status
    if job.get("receipts"):status="published_reported" if job["receipts"][-1].get("url") else "status_unknown"
    view.update(status=status,status_label=STATE_NAMES[status],approval_valid=valid,
                can_confirm=not blockers and not pending,
                local_package_ready=all(x["status"]!="blocked" for x in view["preflight"] if x["key"] in {"media_file","title","body","placeholders","cover"}))
    view["preparation"]=("文案已写" if r["title"] and r["body"] else "文案待准备")+"；"+("封面PNG已生成" if cover_available(cover_for(job,r)) else "封面未生成")+"；"+("平台草稿已核实" if status=="draft_filled" else "平台草稿未完成")
    if status=="published_reported":view["preparation"]="已登记外部发布链接；人工反馈尚未回查"
    elif status=="status_unknown":view["preparation"]="执行状态未知；先核查平台，不自动重发"
    return view


def append_revision(job, patch, stamp):
    current=copy.deepcopy(job["revisions"][-1]) if job["revisions"] else {"title":"","body":"","tags":[],"account_name":"","account_url":"","scheduled_at":"","cover_id":None,"checks":{}}
    current.update(copy.deepcopy(patch))
    current["hash"]=revision_hash(job,current)
    # Any material text/account/media/cover change requires the five checks and approval again.
    if job["revisions"] and current["hash"]!=job["revisions"][-1]["hash"]:current["checks"]={}
    current.update(number=len(job["revisions"])+1,created_at=stamp)
    job["revisions"].append(current);job["updated_at"]=stamp
    return current


def create_job(files,payload,stamp):
    def change(data):
        p=project(data);action=None;source=None
        if payload.get("plan_id"):
            plan=next((p for p in data["weekly_plans"] if p["id"]==payload["plan_id"] and p["project_id"]==data["active_project_id"]),None)
            action=next((a for a in plan["actions"] if a["id"]==payload.get("action_id") and a["kind"]=="content"),None) if plan else None
            if not action:raise ValueError("当前项目没有这张内容行动卡")
            source={"plan_id":plan["id"],"action_id":action["id"],"action_key":action["key"]}
        selected=platform(payload.get("platform") or (action["package"].get("platform") if action else None) or "xiaohongshu")["id"]
        asset_id=payload.get("asset_id") or (action["materials"][0]["asset_id"] if action else None)
        asset=next((a for a in p["asset_references"] if a["id"]==asset_id),None)
        if not asset or asset.get('type')!='video' or not asset.get('locator','').lower().endswith('.mp4') or not local_available(asset):raise ValueError("请选择已登记、版本仍有效的本地MP4")
        if action and not any(m["asset_id"]==asset_id and m["version"]==asset["version"] for m in action["materials"]):raise ValueError("行动卡素材版本已变化，需重新评估")
        old=next((j for j in reversed(data["publication_jobs"]) if j["platform"]==selected and j["project_id"]==p["id"] and j["asset_id"]==asset_id and j["asset_version"]==asset["version"] and j.get("source_action")==source and not j.get("receipts")),None)
        if old:return old
        job={"id":uuid4().hex[:12],"project_id":p["id"],"asset_id":asset_id,"asset_version":asset["version"],"platform":selected,
             "created_at":stamp,"updated_at":stamp,"source_action":source,"revisions":[],"covers":[],"title_candidates":[],"brief":{},
             "evidence":action.get("basis",[]) if action else [{"type":"project","id":p["id"]}],
             "editorial_review":[],"approval":None,"draft":{"status":"not_filled"},"receipts":[],"method":METHOD,
             "request_status":"waiting_codex" if not action else "content_imported","events":[]}
        package=action["package"] if action and platform(action["package"].get("platform","xiaohongshu"))["id"]==selected else {}
        if not package:job["request_status"]="waiting_codex"
        if selected=="douyin":job["method"]={**METHOD,"mode":"复用内容简报与事实自检，抖音描述单独适配；未执行或宣称已验证平台写操作"}
        append_revision(job,{"title":package.get("title",""),"body":package.get("body",""),"tags":package.get("tags",[]),"scheduled_at":action.get("scheduled_at","") if action else ""},stamp)
        job["events"].append({"at":stamp,"message":"由同平台内容行动卡导入文案，封面与确认单独准备" if package else "创建平台独立准备任务，等待Codex根据项目与成片写作；未调用后台LLM"})
        data["publication_jobs"].append(job)
        return job
    return files.change(change)


def expected(job,payload):
    if payload.get("expected_revision")!=job["revisions"][-1]["number"]:
        raise ValueError("发布包已出现新版本，请保留本地修改并重新载入后比较；旧版本没有覆盖")


def edit_job(files,payload,stamp):
    def change(data):
        job=job_for(data,payload["id"]);expected(job,payload)
        if any(e.get("url") for e in job["receipts"]):raise ValueError("该包已有发布记录；如需修改，请为新版本建立独立发布包，保留原记录")
        patch={k:payload[k] for k in ("title","body","tags","account_name","account_url","scheduled_at","cover_id","checks") if k in payload}
        for key in ("title","body","account_name","account_url","scheduled_at"):
            if key in patch and (not isinstance(patch[key],str) or len(patch[key])>10000):raise ValueError("文案/账号字段无效或过长")
        if "tags" in patch:
            if not isinstance(patch["tags"],list) or any(not isinstance(t,str) or not t.startswith("#") or len(t)>80 or any(c.isspace() for c in t) for t in patch["tags"]):raise ValueError("标签需为以#开头、无空格的列表")
            patch["tags"]=list(dict.fromkeys(patch["tags"]))
        if "account_url" in patch:patch["account_url"]=profile_url(patch["account_url"],job["platform"])
        if patch.get("scheduled_at"):instant(patch["scheduled_at"])
        if patch.get("cover_id") and not any(c["id"]==patch["cover_id"] and c["asset_version"]==job["asset_version"] for c in job["covers"]):raise ValueError("封面不属于这个素材版本")
        if "checks" in patch and (not isinstance(patch["checks"],dict) or any(k not in CHECKS or type(v) is not bool for k,v in patch["checks"].items())):raise ValueError("人工核对字段无效")
        if "title_candidates" in payload:
            if not isinstance(payload["title_candidates"],list) or len(payload["title_candidates"])>12:raise ValueError("标题候选需为少量列表")
            for row in payload["title_candidates"]:
                if any(not isinstance(row.get(k),str) or not row[k].strip() for k in ("title","method","reason","tradeoff")):raise ValueError("标题候选需解释方法、理由与取舍")
            job["title_candidates"]=copy.deepcopy(payload["title_candidates"])
        for key in ("brief","editorial_review"):
            if key in payload:
                if not isinstance(payload[key],dict if key=="brief" else list):raise ValueError("内容简报或自检格式无效")
                job[key]=copy.deepcopy(payload[key])
        if "platform_evidence" in payload:
            evidence=copy.deepcopy(payload["platform_evidence"])
            if (not isinstance(evidence,dict) or urlsplit(evidence.get("url","")).hostname!=platform(job["platform"])["creator_host"]
                    or not evidence.get("excerpt") or not evidence.get("read_at")
                    or type(evidence.get("max_video_seconds")) not in {int,float} or evidence["max_video_seconds"]<=0
                    or type(evidence.get("max_video_bytes")) is not int or evidence["max_video_bytes"]<=0):
                raise ValueError("上传规则需有平台原始地址、读取时间、短证据与实际读到的限制")
            if not timedelta(0)<=datetime.now(TZ)-instant(evidence["read_at"])<=timedelta(days=7):raise ValueError("平台规则证据需为近期实际读取")
            job["platform_evidence"]=evidence
        r=append_revision(job,patch,stamp);job["request_status"]="prepared" if r["title"] and r["body"] else "waiting_codex"
        job["events"].append({"at":stamp,"message":"保存发布包版本 "+str(r["number"])+"；实质内容变化会使确认失效"})
        return job
    return files.change(change)


def generate_cover(files,payload,stamp):
    data=files.load();job=job_for(data,payload["id"]);expected(job,payload);asset=copy.deepcopy(asset_for(data,job))
    if any(e.get("url") for e in job["receipts"]):raise ValueError("已发布的版本保持原样；请为新用途建立独立发布包")
    if not asset or asset["version"]!=job["asset_version"]:raise ValueError("素材版本已变化")
    from covers import make_cover
    cover_id=uuid4().hex[:12]
    directory=files.path.parent/"publications"/job["id"]/"covers"/cover_id
    cover=make_cover(asset,directory,payload["frame_seconds"],payload["headline"],payload.get("subtitle","作品世界观预告"),project(data,job["project_id"])["name"],platform(job["platform"])["cover_height"])
    cover.update(id=cover_id,created_at=stamp)
    def change(data):
        current=job_for(data,job["id"]);expected(current,payload)
        active_asset=asset_for(data,current)
        if not active_asset or not local_available(active_asset,current["asset_version"]):raise ValueError("素材在生成时发生变化")
        current["covers"].append(cover)
        append_revision(current,{"cover_id":cover_id},stamp)
        current["events"].append({"at":stamp,"message":"从原片 "+str(cover["frame_seconds"])+" 秒生成封面PNG；未重剪或覆写视频"})
        return cover
    return files.change(change)


def approve_job(files,payload,stamp):
    def change(data):
        job=job_for(data,payload["id"]);expected(job,payload);view=view_job(data,job)
        if not view["can_confirm"]:raise ValueError("发布包仍有缺项或人工核对未完成，请先查看自检")
        r=job["revisions"][-1]
        if payload.get("revision_hash")!=r["hash"]:raise ValueError("确认必须对应当前内容版本")
        # Rehash once at confirmation, rather than reading large media on every UI refresh.
        with Path(asset_for(data,job)["locator"]).open("rb") as stream:digest="sha256:"+hashlib.file_digest(stream,"sha256").hexdigest()
        if digest!=job["asset_version"]:raise ValueError("视频文件内容已变化，原版本不能确认")
        job["approval"]={"revision_hash":r["hash"],"revision":r["number"],"account_url":r["account_url"],"at":stamp,
                         "scope":"package_review_only","note":"确认此版发布包；不等于正式发布授权，不执行平台动作"}
        job["events"].append({"at":stamp,"message":"用户确认本版发布包（仅本地记录，未发布或上传）"})
        return job["approval"]
    return files.change(change)


def request_draft(files,payload,stamp):
    def change(data):
        job=job_for(data,payload["id"]);expected(job,payload);view=view_job(data,job)
        if not view["approval_valid"]:raise ValueError("需先核对并确认当前账号、素材、文案和封面版本")
        if job.get("receipts") or job["draft"].get("status") in {"unknown","filled"}:raise ValueError("已有执行记录，先核查状态，不能直接重复填写")
        if job["draft"].get("status")=="requested" and job["draft"].get("revision_hash")==view["current"]["hash"]:return job["draft"]
        attempts=job["draft"].get("attempts",0) if job["draft"].get("revision_hash")==view["current"]["hash"] else 0
        if attempts>=2:raise ValueError("同版草稿填写已尝试两次，请先处理阻塞并核查平台状态")
        job["draft"]={"status":"requested","revision_hash":view["current"]["hash"],"requested_at":stamp,
                      "task_id":uuid4().hex[:10],"scope":"draft_only","execution":"waiting_codex","attempts":attempts+1,
                      "note":"仅保存给当前Codex的填写任务；网页没有后台浏览器，禁止正式发布。上传前核对账号并取得本次外部传输授权。"}
        job["events"].append({"at":stamp,"message":"保存草稿填写任务；等待Codex实际操作，未执行上传或发布"})
        return job["draft"]
    return files.change(change)


def record_execution(files,payload,stamp):
    def change(data):
        job=job_for(data,payload["id"]);expected(job,payload);r=job["revisions"][-1]
        kind=payload.get("kind");note=payload.get("note","")
        if not isinstance(note,str) or not note.strip():raise ValueError("需说明实际观察/人工登记依据")
        if kind in {"draft_filled","draft_blocked","draft_unknown"}:
            if job["draft"].get("status") not in {"requested","unknown","blocked"} or job["draft"].get("revision_hash")!=r["hash"]:raise ValueError("没有对应版本的草稿执行任务")
            evidence=payload.get("evidence",{})
            if kind=="draft_filled" and (evidence.get("source")!="platform_ui" or evidence.get("account_url")!=r["account_url"] or not evidence.get("screenshot") or not Path(evidence["screenshot"]).is_file()):raise ValueError("平台草稿完成需实际界面证据、截图与匹配账号，不能由本地包推断")
            job["draft"].update(status={"draft_filled":"filled","draft_blocked":"blocked","draft_unknown":"unknown"}[kind],
                                note=note,evidence=evidence,checked_at=stamp,execution="observed")
        elif kind in {"published_reported","unknown"}:
            url=payload.get("url","")
            if kind=="published_reported":
                url=content_url(url,job["platform"])
            entry={"kind":kind,"url":url if kind=="published_reported" else None,"at":stamp,"note":note,
                   "revision_hash":r["hash"],"revision":r["number"],"source":"manual_report","account_url":r["account_url"]}
            if any(e.get("url")==entry["url"] and e["revision_hash"]==entry["revision_hash"] and e["kind"]==kind for e in job["receipts"]):return job
            job["receipts"].append(entry)
            asset=asset_for(data,job)
            if asset and url and kind=="published_reported":
                asset["published"]=True;asset.setdefault("publication_history",[]).append({**entry,"job_id":job["id"],"platform":job["platform"],"asset_version":job["asset_version"]})
        else:raise ValueError("执行结果类型无效")
        job["events"].append({"at":stamp,"message":"登记执行结果："+kind+"；"+note})
        return job
    return files.change(change)


def package_text(view):
    r=view["current"];asset=view["asset"] or {}
    lines=["# "+(r["title"] or "尚未完成的发布包"),"", "平台："+platform(view["platform"])["name"], "账号："+(r["account_name"] or "未指定"),
           "账号主页："+(r["account_url"] or "未指定"),"状态："+view["status_label"],"版本："+str(r["number"]),
           "版本指纹："+r["hash"],"", "## 正文",r["body"],"", " ".join(r["tags"]),"", "## 素材",
           asset.get("locator","素材已移除"),"素材版本："+view["asset_version"],"", "## 检查结果"]
    lines += ["- "+x["label"]+"："+x["status"]+"；"+x["note"] for x in view["preflight"]]
    lines += ["", "## 还需执行", "- 在目标平台核对实际登录账号、字段计数、视频规格、AI标识和预览。",
              "- 草稿未填写时，仍需上传视频、封面并填写文案/选择话题；本地预览与标签文本不代表平台话题已挂载。",
              "- 正式发布前需单独确认具体账号、素材、文案和封面。状态未知时先查记录，禁止盲目重发。",
              "", "## 方法来源", METHOD["name"],"https://github.com/SpaceZephyr/creator-buddy/tree/"+METHOD["commit"],METHOD["mode"]]
    return "\n".join(lines)+"\n"


def package_zip(data, job):
    view=view_job(data,job)
    if not view["local_package_ready"]:raise ValueError("文案、素材或封面文件尚不完整，不能导出完整发布包")
    stream=tempfile.SpooledTemporaryFile(max_size=8*1024*1024,mode="w+b")
    try:
        r=view["current"];cover=cover_for(job,r)
        with zipfile.ZipFile(stream,"w",compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            digest=hashlib.sha256()
            with Path(view["asset"]["locator"]).open("rb") as source, archive.open("media/"+Path(view["asset"]["locator"]).name,"w",force_zip64=True) as destination:
                while chunk:=source.read(1024*1024):
                    digest.update(chunk);destination.write(chunk)
            if "sha256:"+digest.hexdigest()!=job["asset_version"] or not local_available(view["asset"],job["asset_version"]):raise ValueError("打包时原片内容或版本发生变化，请重新读取")
            cover_bytes=Path(cover["path"]).read_bytes()
            if hashlib.sha256(cover_bytes).hexdigest()!=cover["sha256"]:raise ValueError("打包时封面文件发生变化")
            archive.writestr("cover.png",cover_bytes)
            archive.writestr("title.txt",r["title"])
            archive.writestr("body.txt",r["body"]+"\n\n"+" ".join(r["tags"]))
            archive.writestr("README.md",package_text(view))
            archive.writestr("manifest.json",json.dumps({"job_id":job["id"],"revision":r["number"],"revision_hash":r["hash"],
                "asset_version":job["asset_version"],"cover_sha256":cover["sha256"],"platform":job["platform"],"account_url":r["account_url"],
                "status":view["status"],"approval_valid":view["approval_valid"],"draft":job["draft"]},ensure_ascii=False,indent=2))
        stream.seek(0)
        return stream
    except Exception:
        stream.close();raise


def export_publications(data,directory,cell):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["项目","平台","素材","标题","账号","状态","本地包齐全","平台草稿","内容版本","最近更新"])
    for job in data["publication_jobs"]:
        view=view_job(data,job);r=view["current"]
        writer.writerow([cell(v) for v in [project(data,job["project_id"])["name"],platform(job["platform"])["name"],(view["asset"] or {}).get("title","已移除素材"),r["title"],r["account_name"],
                                          view["status_label"],view["local_package_ready"],job["draft"]["status"],r["number"],job["updated_at"]]])
        folder=Path(directory)/"publications"/job["id"];folder.mkdir(parents=True,exist_ok=True)
        (folder/"发布包说明.md").write_text(package_text(view),encoding="utf-8")
        (folder/"publication.json").write_text(json.dumps(job,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (folder/"title.txt").write_text(r["title"],encoding="utf-8")
        (folder/"body.txt").write_text(r["body"]+"\n\n"+" ".join(r["tags"]),encoding="utf-8")
    (Path(directory)/"发布准备.csv").write_text(stream.getvalue(),encoding="utf-8-sig",newline="")
