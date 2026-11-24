"""Small, platform-scoped observation snapshots; no crawler or trend claims."""
import copy
import csv
from uuid import uuid4
from platforms import platform, content_url
from workflow import project, instant
from access_links import remember_links,resolve_url,url_map

CAPABILITIES={"search":"站内搜索","detail":"作品正文与互动数据","peer":"同行主页观察","draft":"平台草稿填写"}


def record_check(files,payload,stamp):
    row=copy.deepcopy(payload)
    row["platform"]=platform(row["platform"])["id"]
    if row.get("capability") not in CAPABILITIES or row.get("status") not in {"verified","blocked","untested"}:
        raise ValueError("平台检查类型或状态无效")
    if not isinstance(row.get("note"),str) or not row["note"].strip():raise ValueError("平台检查需说明实际结果")
    if row["status"]=="verified":
        if not row.get("url") or not row.get("excerpt") or not row.get("read_at"):raise ValueError("实测通过需实际读取地址、时间与证据")
        from platforms import detect_platform
        if detect_platform(row["url"])!=row["platform"]:raise ValueError("检查证据平台不一致")
        instant(row["read_at"])
    def change(data):
        remember_links(data,payload,project(data)['id'],stamp,'platform_check')
        row.update(id=uuid4().hex[:12],project_id=project(data)["id"],checked_at=stamp)
        data["platform_checks"].append(row)
        return row
    return files.change(change)


def record_snapshot(files,payload,stamp):
    row=copy.deepcopy(payload);row["platform"]=platform(row["platform"])["id"]
    if row.get("source_type") not in {"platform_browser","web_index","manual"}:raise ValueError("观察需标明真实获取方式")
    if any(not isinstance(row.get(k),str) or not row[k].strip() for k in ("query","sort","time_window","scope_note")):
        raise ValueError("观察需说明查询、排序、时间范围与采样限制")
    if not isinstance(row.get("items"),list) or not 1<=len(row["items"])<=40:raise ValueError("观察需1–40条真实记录")
    seen=set()
    for item in row["items"]:
        item["url"]=content_url(item["url"],row["platform"])
        if item["url"] in seen:raise ValueError("同一快照不能重复计算作品")
        seen.add(item["url"])
        if not item.get("title"):raise ValueError("记录需有来源中读到的标题")
        if item.get("published_at"):instant(item["published_at"])
        item.setdefault("published_at",None);item.setdefault("body_read",False)
        if type(item["body_read"]) is not bool:raise ValueError("正文读取状态必须明确")
        metrics=item.setdefault("metrics",{})
        for key in ("likes","comments","shares","favorites"):
            value=metrics.setdefault(key,None)
            if value is not None and (type(value) is not int or value<0):raise ValueError("未知互动量留空；已知量须为非负整数")
        if row["source_type"]=="web_index" and (item["body_read"] or any(v is not None for v in metrics.values())):
            raise ValueError("搜索摘要不能冒充原帖阅读或平台实时互动量")
    def change(data):
        remember_links(data,payload,project(data)['id'],stamp,'research_snapshot')
        row.update(id=uuid4().hex[:12],project_id=project(data)["id"],observed_at=stamp)
        data["research_snapshots"].append(row)
        return row
    return files.change(change)


def catalog(data,configs):
    result=[]
    for config in configs:
        checks=[]
        for key,name in CAPABILITIES.items():
            latest=next((r for r in reversed(data["platform_checks"]) if r["platform"]==config["id"] and r["capability"]==key),None)
            checks.append(latest or {"capability":key,"status":"untested","note":"适配已接入；本轮尚未实际验证"})
            checks[-1]={**checks[-1],"label":name}
        result.append({**config,"checks":checks})
    return result


def export_research(data,directory,cell):
    with open(directory/"平台观察样本.csv","w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(["项目","平台","关键词","来源方式","排序","时间范围","采集时间","作品","链接","发布时间","已读正文","点赞","评论","分享","收藏","采样限制"])
        for row in data["research_snapshots"]:
            for item in row["items"]:
                writer.writerow([cell(v) for v in [project(data,row["project_id"])["name"],platform(row["platform"])["name"],row["query"],row["source_type"],row["sort"],row["time_window"],row["observed_at"],item["title"],resolve_url(item["url"],url_map(data,row['project_id'])),item["published_at"],item["body_read"],*[item["metrics"].get(k) for k in ("likes","comments","shares","favorites")],row["scope_note"]]])
