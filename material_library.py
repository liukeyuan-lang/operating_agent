"""User-managed global material packs; no exploration-project binding."""
from pathlib import Path
from uuid import uuid4
import copy
from material_understanding import asset_metadata


def add_pack(files,payload,service,at):
    bound=service.bind(payload.get('material_directory'),payload.get('material_analysis_id'))
    metadata=[asset_metadata(e) for e in bound['files']]
    if any(m['version']!='sha256:'+e['sha256'] for m,e in zip(metadata,bound['files'])):raise ValueError('素材已变化，请重新理解')
    name=payload.get('name','')
    if not isinstance(name,str) or len(name)>200:raise ValueError('素材包名称无效')
    def action(data):
        pack=next((r for r in data['material_packs'] if r.get('fingerprint')==bound['fingerprint']),None)
        if pack is None:
            pack={'id':uuid4().hex[:12],'created_at':at};data['material_packs'].append(pack)
        assets=[]
        for entry,m in zip(bound['files'],metadata):
            assets.append({**m,'id':'library-'+uuid4().hex[:12],'title':Path(entry['relative_path']).stem,'file_id':entry['sha256']})
        pack.update(name=name.strip() or bound['understanding']['title'],directory=bound['directory'],fingerprint=bound['fingerprint'],
                    analysis_id=bound['analysis_id'],assets=assets,deleted=False,updated_at=at)
        return pack
    return files.change(action)


def delete_pack(files,pack_id,at):
    def action(data):
        pack=next((p for p in data['material_packs'] if p['id']==pack_id),None)
        if not pack:raise ValueError('素材包不存在')
        pack.update(deleted=True,deleted_at=at)
        return {'id':pack_id,'deleted':True}
    return files.change(action)


def view_packs(data,catalog):
    analyses={a['id']:a for a in catalog.get('analyses',[])}
    result=[]
    for p in data.get('material_packs',[]):
        if p.get('deleted'):continue
        row=copy.deepcopy(p);a=analyses.get(p.get('analysis_id'),{})
        row['understanding']=a.get('description');row['understanding_status']=a.get('status','missing')
        result.append(row)
    return result
