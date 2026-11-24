"""Weekly decisions and evidence. Codex supplies judgment; these rules keep it honest."""
import copy
import csv
import io
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from media import local_available
from workflow import TZ, classify, instant, profile_digest, project
from platforms import detect_platform,platform

KINDS = {"content":"内容制作/发布准备", "opportunity":"机会参与准备", "prepare":"补充/复用素材", "verify":"机会核验"}
DIMENSIONS = {"topics":"话题与时效", "peers":"同行观察", "opportunities":"资源机会", "assets":"素材复用与缺口"}


def next_week(at=None):
    today = (instant(at) if at else datetime.now(TZ)).astimezone(TZ).date()
    return (today+timedelta(days=7-today.weekday())).isoformat()


def text_field(obj, key):
    if not isinstance(obj.get(key), str) or not obj[key].strip():
        raise ValueError("缺少 "+key)


def http_link(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("证据链接需为 HTTP(S)")
    return value


def signal_state(signal, at=None):
    current = instant(at) if at else datetime.now(TZ)
    heat = signal.get("heat", {})
    if heat.get("status") == "platform_ranked":
        proof = max((e for e in signal["evidence"] if e["url"] == heat.get("source_url")), key=lambda e:instant(e["read_at"]), default=None)
        if proof and timedelta(0) <= current-instant(proof["read_at"]) <= timedelta(days=7):
            return "平台榜单观察"
        return "榜单证据需更新"
    return {"topic":"选题线索 · 热度未证实", "peer_pattern":"同行启发 · 不代表热点", "asset_gap":"素材缺口"}[signal["kind"]]


def record_signals(data, run, rows, stamp):
    for raw in rows:
        row = copy.deepcopy(raw)
        for key in ("key", "title", "summary", "fit_reason"):
            text_field(row, key)
        if row.get("kind") not in {"topic", "peer_pattern", "asset_gap"}:
            raise ValueError("观察类型需为 topic / peer_pattern / asset_gap")
        if not row.get("evidence"):
            raise ValueError("话题/同行/素材判断需有实际来源")
        for proof in row["evidence"]:
            for key in ("url", "read_at", "excerpt", "title"):
                text_field(proof, key)
            http_link(proof["url"])
            if instant(proof["read_at"]) > instant(stamp)+timedelta(minutes=5):
                raise ValueError("证据读取时间不能在未来")
        heat = row.setdefault("heat", {"status":"unverified"})
        inferred=next((detect_platform(e["url"]) for e in row["evidence"] if detect_platform(e["url"])!="web"),"web")
        row["platform"]=platform(row["platform"])["id"] if row.get("platform") and row["platform"]!="web" else inferred
        if inferred!="web" and row["platform"]!=inferred:raise ValueError("观察平台与来源链接不一致")
        if heat.get("status") not in {"unverified", "platform_ranked"}:
            raise ValueError("热度只能记录未证实或有平台榜单证据")
        if heat["status"] == "platform_ranked":
            proof = next((e for e in row["evidence"] if e["url"] == heat.get("source_url")), None)
            if (not proof or proof.get("authority") != "platform" or type(heat.get("rank")) is not int
                or heat["rank"] < 1 or not heat.get("evidence") or heat["evidence"] not in proof["excerpt"]
                or (instant(stamp)-instant(proof["read_at"])) > timedelta(days=7)):
                raise ValueError("热点判断需平台原始榜单、实际名次及短证据；单篇高赞帖不足")
        old = next((s for s in data["signals"] if s["project_id"] == run["project_id"] and s["key"] == row["key"] and s["platform"]==row["platform"]), None)
        row.update(project_id=run["project_id"], updated_at=stamp)
        if old:
            proofs = old["evidence"]+[p for p in row["evidence"] if p not in old["evidence"]]
            old.update({k:v for k,v in row.items() if k not in {"id","first_seen_at","run_ids"}})
            old["evidence"] = proofs
            old["run_ids"] = list(dict.fromkeys(old["run_ids"]+[run["id"]]))
        else:
            row.update(id=uuid4().hex[:10], first_seen_at=stamp, run_ids=[run["id"]])
            data["signals"].append(row)
            run["new_signals"]=run.get("new_signals",0)+1


def resolve_basis(data, profile, refs, strict=True):
    rows = []
    if not refs:
        raise ValueError("行动需关联项目资料、实际观察或机会证据")
    for ref in refs:
        kind = ref.get("type")
        if kind == "project" and ref.get("id") == profile["id"]:
            rows.append({"type":kind,"title":profile["name"],"note":profile["direction"],"url":None})
            continue
        collection = {"item":"items", "signal":"signals"}.get(kind)
        row = next((r for r in data.get(collection, []) if r["id"] == ref.get("id") and r["project_id"] == profile["id"]), None)
        if not row:
            if strict:raise ValueError("行动引用不存在或属于其他项目")
            rows.append({"type":"removed","title":"原依据已移除","note":"需要重新评估","url":None})
            continue
        rows.append({"type":kind, "id":row["id"], "title":row["title"], "url":row.get("url"),
                     "note":row.get("fit_reason"), "evidence":row.get("evidence", [])})
    return rows


def action_issues(data, plan, action, at=None):
    profile = project(data, plan["project_id"])
    current = instant(at) if at else datetime.now(TZ)
    issues = []
    if plan["profile_digest"] != profile_digest(profile):
        issues.append("项目资料已变化，需重新判断这份计划")
    if current.astimezone(TZ).date() >= date.fromisoformat(plan["week_start"])+timedelta(days=7):
        issues.append("计划周已结束，需生成新一周建议")
    for ref in action["basis"]:
        if ref["type"] == "item" and action["kind"] == "opportunity":
            item = next((i for i in data["items"] if i["id"] == ref["id"]),None)
            if not item:
                issues.append("机会记录已移除，需重新核验")
                continue
            bucket, reasons = classify(item, profile, at)
            if bucket != "result" or item["review"]["status"] == "skipped":
                issues.append("机会当前不可直接参与："+"；".join(reasons or ["已被人工排除"]))
        if ref["type"] == "signal":
            signal = next((s for s in data["signals"] if s["id"] == ref["id"]),None)
            if not signal:
                issues.append("选题观察已移除，需重新核验")
                continue
            if action.get("timely") and (signal_state(signal, at) == "榜单证据需更新"
                    or current-max(instant(e["read_at"]) for e in signal["evidence"]) > timedelta(days=7)):
                issues.append("时效选题的观察证据需重新读取")
    for material in action.get("materials", []):
        asset = next((a for a in profile["asset_references"] if a["id"] == material["asset_id"]),None)
        if not asset:
            issues.append("计划使用的素材已从档案移除")
            continue
        if asset.get("version") != material["version"]:
            issues.append("素材版本已变化："+asset["title"])
        elif asset.get("availability") == "local" and not local_available(asset, material["version"]):
            issues.append("本地素材已移动或修改："+asset["title"])
    return list(dict.fromkeys(issues))


def save_plan(files, payload, stamp):
    def change(data):
        profile = project(data, payload.get("project_id"))
        if payload.get("profile_digest") != profile_digest(profile):
            raise ValueError("周计划必须绑定当前项目资料摘要")
        week = date.fromisoformat(payload["week_start"])
        if week.weekday() != 0:
            raise ValueError("week_start 需为周一")
        actions = copy.deepcopy(payload.get("actions", []))
        if len(actions) > 3:
            raise ValueError("首屏只选最多3个值得做的任务；其他候选保留在库中")
        if not actions and not payload.get("no_action_reason"):
            raise ValueError("没有推荐时需说明为何本轮不新增投入")
        coverage = payload.get("assessment", {})
        for dimension in DIMENSIONS:
            if coverage.get(dimension, {}).get("status") not in {"reviewed", "insufficient"} or not coverage[dimension].get("note"):
                raise ValueError("周计划需评价话题、同行、机会和素材；证据不足如实说明")
        run_ids = payload.get("run_ids", [])
        if any(not any(r["id"] == rid and r["project_id"] == profile["id"] for r in data["runs"]) for rid in run_ids):
            raise ValueError("计划轮次不存在或属于其他项目")
        keys = set()
        for action in actions:
            for key in ("key", "title", "reason", "scheduled_at"):
                text_field(action, key)
            if not re.fullmatch(r"[a-z0-9-]{1,80}", action["key"]) or action["key"] in keys:
                raise ValueError("每个行动需独立、稳定的英文 key")
            keys.add(action["key"])
            if action.get("kind") not in KINDS:
                raise ValueError("未知行动类型")
            scheduled = instant(action["scheduled_at"]).astimezone(TZ).date()
            if not week <= scheduled < week+timedelta(days=7):
                raise ValueError("建议处理时间需位于计划周内")
            resolve_basis(data, profile, action.get("basis"))
            if action["kind"] == "opportunity" and not any(r["type"] == "item" for r in action["basis"]):
                raise ValueError("参与准备必须有已核实的机会")
            effort = action.get("effort_hours", {})
            if any(type(effort.get(k)) not in {int, float} for k in ("min", "max")) or not 0 <= effort["min"] <= effort["max"]:
                raise ValueError("工时需为合理估计区间，不代表团队已承诺")
            for key in ("steps", "remaining_work", "confirmations", "risks", "reuse"):
                if not isinstance(action.get(key), list) or not action[key] or any(not isinstance(t, str) or not t.strip() for t in action[key]):
                    raise ValueError("行动需列出 "+key)
            for material in action.setdefault("materials", []):
                asset = next((a for a in profile["asset_references"] if a["id"] == material.get("asset_id")), None)
                if not asset or asset.get("version") != material.get("version"):
                    raise ValueError("行动素材需绑定当前项目的确切版本")
            package = action.setdefault("package", {})
            if action["kind"] == "content":
                for key in ("platform", "title", "body", "cover_brief"):
                    text_field(package, key)
                package["platform"]=platform(package["platform"])["id"]
                if not package.get("tags") or not action["materials"]:
                    raise ValueError("内容行动需准备标签并关联具体素材；缺媒体时用prepare行动")
            elif not package.get("brief"):
                raise ValueError("需准备任务说明或可检查的材料")
            # This demo has no platform editor connector. Never accept a fabricated draft receipt.
            if package.get("platform_draft", "not_filled") != "not_filled":
                raise ValueError("尚未接入平台草稿填写，不能宣称已填好")
            package["platform_draft"] = "not_filled"
            action["id"] = uuid4().hex[:12]
            previous = next((a for p in reversed(data["weekly_plans"]) if p["project_id"] == profile["id"]
                             for a in p["actions"] if a["key"] == action["key"]), None)
            action["review"] = copy.deepcopy(previous["review"]) if previous else {"status":"pending", "note":""}
        plan = {"id":uuid4().hex[:12], "project_id":profile["id"], "week_start":week.isoformat(),
                "profile_digest":profile_digest(profile), "created_at":stamp, "run_ids":run_ids,
                "assessment":copy.deepcopy(coverage), "actions":actions, "summary":payload.get("summary", ""),
                "no_action_reason":payload.get("no_action_reason"), "scope_note":payload.get("scope_note", "")}
        for action in actions:
            issues = action_issues(data, plan, action, stamp)
            if issues:
                raise ValueError("不能保存失效行动："+"；".join(issues))
        data["weekly_plans"].append(plan)
        return plan
    return files.change(change)


def plan_view(data):
    result = copy.deepcopy(data["weekly_plans"][-1]) if data["weekly_plans"] else None
    if not result:
        return None
    profile = data["current_project"]
    result["issues"]=[]
    if result["profile_digest"] != profile_digest(profile):result["issues"].append("项目资料已变化，需重新判断周计划")
    if datetime.now(TZ).date() >= date.fromisoformat(result["week_start"])+timedelta(days=7):result["issues"].append("这份计划周已结束，需生成新一周建议")
    for action in result["actions"]:
        action["issues"] = action_issues(data, result, action)
        action["sources"] = resolve_basis(data, profile, action["basis"],strict=False)
        action["material_details"]=[]
        for m in action["materials"]:
            asset=next((a for a in profile["asset_references"] if a["id"]==m["asset_id"]),
                       {"id":m["asset_id"],"title":"已移除素材","locator":"项目资料中已移除","version":m["version"]})
            action["material_details"].append({**asset,"selected_version":m["version"],"purpose":m.get("purpose",""),"file_available":local_available(asset,m["version"])})
        if action["kind"] == "content":
            available = sum(a["file_available"] for a in action["material_details"])
            action["preparation"] = "文案/封面方案已写；媒体文件 "+str(available)+"/"+str(len(action["materials"]))+" 已定位；平台草稿未填写"
            if any(a.get("rights") != "cleared" for a in action["material_details"]):
                action["preparation"] += "；素材授权待确认"
        else:
            action["preparation"] = "任务说明/清单已写；"+("材料见详情" if action["materials"] else "核验尚未完成")
    result["estimated_hours"] = {key:round(sum(a["effort_hours"][key] for a in result["actions"] if a["review"]["status"] != "deferred"), 2) for key in ("min", "max")}
    result["capacity_note"] = "工时为任务工作量估计，具体排期由创作者决定。"
    return result


def review_action(files, payload, stamp):
    def change(data):
        plan = next((p for p in data["weekly_plans"] if p["id"] == payload.get("plan_id") and p["project_id"] == data["active_project_id"]), None)
        action = next((a for a in plan["actions"] if a["id"] == payload.get("action_id")), None) if plan else None
        if not action or payload.get("status") not in {"pending", "kept", "deferred"} or len(payload.get("note", "")) > 2000:
            raise ValueError("行动不存在或内部标记无效")
        action["review"] = {"status":payload["status"], "note":payload.get("note", ""), "at":stamp}
        return action["review"]
    return files.change(change)


def package_markdown(plan, action):
    lines = ["# "+action["title"], "", "计划周："+plan["week_start"], "建议处理："+action["scheduled_at"],
             "内部准备文件；不代表发布或报名已获确认。", "", "## 为什么做", action["reason"]]
    for key, label in (("title", "发布标题"), ("body", "正文草稿"), ("cover_brief", "封面方案"), ("brief", "任务说明")):
        if action["package"].get(key):
            lines.extend(["", "## "+label, action["package"][key]])
    if action["package"].get("tags"):
        lines.extend(["", "标签建议（热度未核实）："+" ".join(action["package"]["tags"])])
    for key, label in (("reuse", "一份素材的用途"), ("steps", "执行步骤"), ("remaining_work", "剩余工作"), ("confirmations", "需确认"), ("risks", "风险与未知"), ("issues", "当前失效条件")):
        if action.get(key):
            lines.extend(["", "## "+label]+["- "+t for t in action[key]])
    lines.extend(["", "## 素材版本"]+["- "+a["title"]+" | "+a["locator"]+" | "+a["selected_version"] for a in action.get("material_details", [])])
    lines.extend(["", "## 依据"]+["- "+s["title"]+("："+s["url"] if s.get("url") else "（项目档案）") for s in action.get("sources", [])])
    return "\n".join(lines)+"\n"


def planning_csv(data, cell):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["项目", "计划周", "行动", "类型", "建议处理", "准备状态", "需要确认", "内部标记", "备注"])
    for p in data["projects"]:
        from workflow import scoped
        view = plan_view(scoped(data, p["id"]))
        if view:
            for a in view["actions"]:
                writer.writerow([cell(v) for v in [p["name"], view["week_start"], a["title"], KINDS[a["kind"]], a["scheduled_at"], a["preparation"], "；".join(a["confirmations"]), a["review"]["status"], a["review"]["note"]]])
    return stream.getvalue()
