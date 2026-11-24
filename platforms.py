"""Platform contracts. Adding a platform does not assert that its browser tools work."""
import copy
import re
from urllib.parse import parse_qsl,urlsplit

PLATFORMS={
    "xiaohongshu":{"id":"xiaohongshu","name":"小红书","channel":"xhs","domains":["xiaohongshu.com"],
        "creator_host":"creator.xiaohongshu.com","home_url":"https://www.xiaohongshu.com/",
        "creator_url":"https://creator.xiaohongshu.com/","profile_example":"https://www.xiaohongshu.com/user/profile/…",
        "title_budget":20,"body_budget":1000,"cover_width":1080,"cover_height":1440,
        "copy_guidance":"项目提问、短段落与相关标签；不套种草文体，不承诺热度。"},
    "douyin":{"id":"douyin","name":"抖音","channel":"douyin","domains":["douyin.com"],
        "creator_host":"creator.douyin.com","home_url":"https://www.douyin.com/jingxuan",
        "creator_url":"https://creator.douyin.com/","profile_example":"https://www.douyin.com/user/…",
        "title_budget":30,"body_budget":500,"cover_width":1080,"cover_height":1920,
        "copy_guidance":"描述先交代这是什么视频，再给具体观看问题；优先简短，不把视频封面变成平台规则，不强行重剪。"}
}
ALIASES={"xhs":"xiaohongshu","小红书":"xiaohongshu","dy":"douyin","抖音":"douyin"}


def platform(value="xiaohongshu"):
    key=ALIASES.get(value,value)
    if key not in PLATFORMS:raise ValueError("未接入的平台："+str(value))
    return copy.deepcopy(PLATFORMS[key])


def platform_list(values):
    if isinstance(values,str):values=values.split(",")
    if not isinstance(values,list) or not values:raise ValueError("请至少选择一个已接入的平台")
    return list(dict.fromkeys(platform(v)["id"] for v in values))


def discovery_catalog():
    return [{k:p[k] for k in ('id','name','channel')} for p in PLATFORMS.values()]+[
        {'id':'web','name':'网页搜索','channel':'web'}]


def discovery_platform_list(values):
    """Search channels include the public web; publishing platforms remain separate."""
    if isinstance(values,str):values=values.split(',')
    if not isinstance(values,list) or not values:raise ValueError('请至少选择一种探索渠道')
    return list(dict.fromkeys('web' if v in {'web','网页','网页搜索'} else platform(v)['id'] for v in values))


def detect_platform(value):
    host=(urlsplit(value).hostname or "").lower()
    for key,p in PLATFORMS.items():
        if any(host==d or host.endswith("."+d) for d in p["domains"]):return key
    return "web"


def content_url(value,selected=None,allow_short=False):
    parsed=urlsplit(value);key=detect_platform(value)
    if parsed.scheme not in {"http","https"} or parsed.username or parsed.password or key=="web":raise ValueError("请使用已接入平台的公开作品链接")
    if selected and key!=platform(selected)["id"]:raise ValueError("链接与指定平台不一致")
    if key=="xiaohongshu":
        match=re.fullmatch(r"/(?:explore|search_result|discovery/item)/([a-fA-F0-9]{24})/?",parsed.path)
        if not match:match=re.fullmatch(r"/user/profile/[a-fA-F0-9]{24}/([a-fA-F0-9]{24})/?",parsed.path)
        if match:return "https://www.xiaohongshu.com/explore/"+match[1].lower()
    elif key=="douyin":
        match=re.fullmatch(r"/(?:video|note)/(\d{10,25})/?",parsed.path)
        if match:return "https://www.douyin.com/"+parsed.path.strip("/")
        modal=dict(parse_qsl(parsed.query)).get("modal_id","")
        if re.fullmatch(r"\d{10,25}",modal):return "https://www.douyin.com/video/"+modal
        if allow_short and parsed.hostname=="v.douyin.com" and re.fullmatch(r"/[A-Za-z0-9_-]+/?",parsed.path):return "https://v.douyin.com"+parsed.path
    raise ValueError("需要实际作品详情链接；首页、搜索页和未展开短链不能当作品回执")


def account_url(value,selected="xiaohongshu"):
    if not value:return ""
    p=platform(selected);parsed=urlsplit(value.strip())
    if parsed.scheme!="https" or parsed.username or parsed.password or parsed.port not in {None,443} or parsed.hostname not in {p["domains"][0],"www."+p["domains"][0]}:
        raise ValueError("请填写"+p["name"]+"的公开账号主页")
    pattern=r"/user/profile/[a-fA-F0-9]{24}/?" if p["id"]=="xiaohongshu" else r"/user/[A-Za-z0-9_.=-]{8,200}/?"
    if not re.fullmatch(pattern,parsed.path):raise ValueError("账号主页路径不正确："+p["profile_example"])
    return "https://www."+p["domains"][0]+parsed.path.rstrip("/")
