"""Self-contained, script-free candidate snapshots. No app state or local media is embedded."""
import base64
import hashlib
from html import escape
import re
from urllib.parse import urlsplit

from homefeed import DIMENSIONS,now

STYLE='''
:root{font:14px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#29382d;background:#f7f8f5}*{box-sizing:border-box}body{margin:0}main{max-width:1220px;margin:auto;padding:42px 32px 60px}header{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:28px}h1{font-size:27px;margin:3px 0 8px;line-height:1.5}h2{font-size:19px;line-height:1.6;margin:14px 0 10px}h3{font-size:14px;margin:20px 0 8px}p{margin:9px 0}.muted{font-size:12px;color:#83907d}.count{white-space:nowrap;padding-top:14px;color:#71816b}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.candidate{align-self:start;background:#fff;border:1px solid #dfe6da;border-radius:11px;padding:22px;min-width:0;overflow-wrap:anywhere}.top,.meta{display:flex;justify-content:space-between;align-items:center;gap:14px}.score{font-size:25px;font-weight:650}.score small{font-size:11px;font-weight:400;color:#929c8b}.badge{font-size:11px;background:#f3eee0;color:#92743c;padding:3px 8px;border-radius:5px}.badge.open{background:#eaf1e6;color:#4e6d46}.badge.closed{background:#efefed;color:#81877b}.brief{color:#718068;font-size:13px}.meta{font-size:12px;color:#7b8973;align-items:flex-start;margin:16px 0}.meta a{white-space:nowrap;flex-shrink:0}a{color:#44664b;text-underline-offset:3px}details>summary{cursor:pointer;color:#5b7155;font-size:12px;user-select:none}details[open]>summary{margin-bottom:12px}.candidate>details{border-top:1px solid #e8ede3;padding-top:13px;margin-top:16px;font-size:13px}.detail-text,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}.rating{border-bottom:1px solid #e8ede4;padding:10px 0}.rating p{color:#79856f;font-size:12px}blockquote{border-left:2px solid #c8d8bd;margin:10px 0;padding-left:12px;color:#7b886f;font-size:12px}.evidence{background:#f4f7ef;padding:13px 15px;margin:10px 0;border-radius:6px}.archive,.weights{margin-top:26px}.weights{padding:14px 18px;border:1px solid #e0e7da;border-radius:8px}.empty{padding:65px 20px;text-align:center;color:#87967c;border:1px dashed #d6dfce;border-radius:9px}footer{border-top:1px solid #e1e7da;margin-top:32px;padding-top:16px;font-size:11px;color:#89947e}ul{padding-left:20px}@media(max-width:800px){.grid{grid-template-columns:1fr}main{padding:24px 18px 40px}header{gap:12px}h1{font-size:23px}.candidate{padding:18px}}@media print{body{background:white}main{padding:0}.grid{display:block}.candidate{break-inside:avoid;margin-bottom:18px}}
'''.strip()


def content_security_policy():
    digest=base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
    return "default-src 'none'; style-src 'sha256-"+digest+"'; base-uri 'none'; form-action 'none'"


def safe_url(value):
    if not isinstance(value,str) or not value or any(c.isspace() or ord(c)<32 for c in value):return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in {'https','http'} or not parsed.hostname or parsed.username or parsed.password:return None
        parsed.port
    except ValueError:return None
    return value


def text(value):
    return escape(str(value if value is not None else ''),quote=True)


def link(value,label):
    target=safe_url(value)
    return '<a href="'+text(target)+'" target="_blank" rel="noopener noreferrer">'+text(label)+' ↗</a>' if target else ''


def candidate(row):
    r=row['ranking'];state=r['status'];label={'open':'正在开放','unknown':'条件待确认','closed':'已截止 / 关闭'}.get(state,'条件待确认')
    css=state if state in {'open','unknown','closed'} else 'unknown'
    parts=['<article class="candidate"><div class="top"><span class="badge '+css+'">'+label+'</span>',
           '<strong class="score">'+text(r['total'])+'<small> / 100</small></strong></div>',
           '<h2>'+text(row['title'])+'</h2><p class="brief">'+text(row['summary'])+'</p>',
           '<div class="meta"><span>截止：'+text(row.get('deadline',{}).get('label') or '未确认')+'</span>'+link(row.get('url'),'原帖')+'</div>',
           '<details><summary>评分、证据与参与条件</summary>',
           '<p class="muted">评估于 '+text(row.get('assessed_at') or '未确认')+'</p>']
    for c in r['components']:
        points='未知' if c.get('score') is None else str(c['points'])+' / '+str(c['weight'])
        parts+=['<div class="rating"><strong>'+text(c['label'])+' '+text(points)+'</strong><p>'+text(c.get('reason'))+'</p>']
        if c.get('evidence'):parts.append('<blockquote>'+text(c['evidence'].get('quote'))+'</blockquote>')
        parts.append('</div>')
    parts+=['<h3>参与条件</h3><p class="detail-text">'+text(row.get('requirements') or '未确认')+'</p>',
            '<p class="detail-text">授权：'+text(row.get('rights') or '未确认')+'</p>',link(row.get('entry_url'),'参与入口')]
    if row.get('uncertainties'):
        parts+=['<h3>待确认</h3><ul>',*['<li>'+text(value)+'</li>' for value in row['uncertainties']],'</ul>']
    parts.append('<h3>原文证据</h3>')
    for doc in row.get('evidence',[]):
        parts+=['<section class="evidence">'+link(doc.get('url'),'官方原文' if doc.get('official') else '发现来源'),
                '<p class="muted">'+text(doc.get('read_at'))+'</p>',
                '<blockquote>'+text(doc.get('excerpt'))+'</blockquote>']
        if doc.get('authority_basis'):parts.append('<p class="muted">来源依据：'+text(doc['authority_basis'])+'</p>')
        parts.append('</section>')
    parts.append('</details></article>')
    return ''.join(parts)


def filename(view,exported_at=None):
    project=view.get('current_project')
    if not project:raise ValueError('请先选择探索项目')
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',project['name']).strip(' .')[:80] or '探索项目'
    day=(exported_at or now())[:10]
    return '候选机会-'+name+'-'+day+'.html'


def render(view,exported_at=None):
    project=view.get('current_project')
    if not project:raise ValueError('请先选择探索项目')
    stamp=exported_at or now()
    rows=[row for row in view.get('opportunities',[]) if row.get('project_id')==project['id']]
    active=[r for r in rows if r['ranking']['status']!='closed'];closed=[r for r in rows if r['ranking']['status']=='closed']
    title='候选机会 · '+project['name']
    parts=['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="'+text(content_security_policy())+'">',
           '<title>'+text(title)+'</title><style>'+STYLE+'</style></head><body><main>',
           '<header><div><p class="muted">候选机会 · 只读快照</p><h1>'+text(project['name'])+'</h1>',
           '<p class="muted">导出于 '+text(stamp)+'</p></div><span class="count">'+str(len(active))+' 条候选</span></header>']
    parts.append('<div class="grid">'+''.join(candidate(row) for row in active)+'</div>' if active else '<div class="empty">暂无候选机会</div>')
    if closed:parts.append('<details class="archive"><summary>已截止 / 关闭（'+str(len(closed))+'）</summary><div class="grid">'+''.join(candidate(row) for row in closed)+'</div></details>')
    parts+=['<details class="weights"><summary>评分说明</summary><p>',
            ' · '.join(text(DIMENSIONS[k])+' '+text(project['weights'][k]) for k in DIMENSIONS),
            '</p><p class="muted">未知项不加分；候选不代表所有参与条件已确认。分数不是获奖概率或预计收入。</p></details>',
            '<footer>这是导出时的静态快照，不会自动更新。页面可离线查看，打开原帖和参与入口需要联网。</footer>',
            '</main></body></html>']
    return ''.join(parts)
