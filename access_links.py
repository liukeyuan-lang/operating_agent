"""Keep real XHS visit URLs separately from stable identity/deduplication keys."""
from urllib.parse import parse_qs,urlsplit

from platforms import account_url,content_url,detect_platform


def access_key(value):
    if not isinstance(value,str) or any(c.isspace() or ord(c)<32 for c in value):return None
    try:
        p=urlsplit(value)
        if p.scheme not in {'http','https'} or p.username or p.password or detect_platform(value)!='xiaohongshu':return None
        if p.port not in {None,80,443}:return None
        try:return content_url(value,'xiaohongshu')
        except ValueError:return account_url(value,'xiaohongshu')
    except ValueError:return None


def signed_url(value):
    if not access_key(value):return False
    token=parse_qs(urlsplit(value).query).get('xsec_token',[''])[0]
    return bool(token and 'redact' not in token.lower() and not any(c in token for c in '<>*…') and token not in {'null','undefined','...'})


def remember_links(data,payload,pid,stamp,source='observed'):
    """Call before normalization. An unsigned URL never replaces a signed URL."""
    rows=data.setdefault('access_links',[]);count=0
    def walk(value):
        nonlocal count
        if isinstance(value,dict):
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
        elif signed_url(value):
            key=access_key(value)
            old=next((r for r in rows if r['project_id']==pid and r['key']==key),None)
            if old and old['url']==value:return
            row={'key':key,'url':value,'project_id':pid,'observed_at':stamp,'source':source}
            if old:old.update(row)
            else:rows.append(row)
            count+=1
    walk(payload)
    return count


def url_map(data,pid):
    return {r['key']:r['url'] for r in data.get('access_links',[]) if r['project_id']==pid and signed_url(r['url']) and access_key(r['url'])==r['key']}


def resolve_url(value,urls):
    return urls.get(access_key(value),value)


def annotate_links(data,pid):
    """Annotate a public-state copy; keep stored URL identities unchanged."""
    urls=url_map(data,pid)
    def walk(node):
        if isinstance(node,dict):
            for value in list(node.values()):walk(value)
            for key in ('url','target','parent_url','author_url'):
                if isinstance(node.get(key),str) and access_key(node[key]):
                    node['access_'+key]=resolve_url(node[key],urls)
                    if key=='url':node['access_status']=access_status(node['access_'+key])
        elif isinstance(node,list):
            for value in node:walk(value)
    walk(data)
    data['access_urls']=urls


def access_status(url):
    key=access_key(url)
    return 'signed' if signed_url(url) else 'needs_refresh' if key and '/explore/' in key else None


def save_links(files,payload,stamp):
    urls=payload.get('urls')
    if not isinstance(urls,list) or not urls or not all(signed_url(u) for u in urls):
        raise ValueError('需提供从实际页面取得的完整小红书链接；不接受空值或脱敏占位符')
    def change(data):
        pid=data['active_project_id']
        count=remember_links(data,urls,pid,stamp,payload.get('source','browser_observed'))
        return {'updated':count,'identities':[access_key(u) for u in urls]}
    return files.change(change)
