"""Related links for an opportunity, without treating every source as official."""
from urllib.parse import urlsplit
import re

from leads import clean_target
from access_links import signed_url,access_status


def related_links(item,resolve=lambda u:u):
    links={}

    def add(url,title,kind,note=''):
        if not isinstance(url,str):return
        url=resolve(url.strip())
        if any(c.isspace() or ord(c)<32 for c in url):return
        try:
            parts=urlsplit(url)
            if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password:return
            parts.port  # Reject invalid port strings before showing a clickable link.
            key=clean_target(url)
        except ValueError:return
        if key not in links:
            links[key]={'url':url,'title':title or parts.hostname,'host':parts.hostname,'kinds':[],'notes':[]}
        row=links[key]
        if signed_url(url):row['url']=url
        row['access_status']=access_status(row['url'])
        if kind not in row['kinds']:row['kinds'].append(kind)
        if note and note not in row['notes']:row['notes'].append(note)

    add(item.get('url'),'发现原帖','发现来源')
    for source in item.get('official_sources',[]):
        add(source.get('url'),source.get('title') or '官方公告','官方来源',source.get('authority_basis',''))
    entry=item.get('facts',{}).get('entry_url',{})
    entry_value=entry.get('url') or entry.get('value','')
    if isinstance(entry_value,str):
        # Older records place a URL and an explanatory sentence in one fact value.
        for url in re.findall(r'''https?://[^\s<>"“”‘’（）]+''',entry_value):
            add(url,'报名入口','报名入口' if entry.get('status')=='confirmed' else '报名入口待核实')
    add(item.get('entry_url'),'报名入口','报名入口待核实')
    add(item.get('author_url'),'发布者主页','账号主页')
    for source in item.get('related_links',[]):
        if isinstance(source,dict):add(source.get('url'),source.get('title') or source.get('label'),'相关资料',source.get('note',''))
    for node in item.get('discovery_path',[]):
        if node.get('kind')=='search':continue
        add(node.get('url'),node.get('label') or '发现路径','发现路径',node.get('reason',''))
    for url in item.get('verification_attempt',{}).get('urls',[]):
        add(url,'查证时访问的入口','核验入口', '曾尝试访问，是否可用见核验进展')
    return sorted(links.values(),key=lambda row:row['access_status']=='needs_refresh')
