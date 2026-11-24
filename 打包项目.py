"""Build a clean source ZIP using an explicit allowlist, never runtime data."""
import argparse
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED,ZipFile

ROOT=Path(__file__).resolve().parent
FILES=(".gitignore","AGENTS.md","demo.py","workflow.py","planning.py","leads.py","verification.py","opportunities.py","access_links.py",
       "media.py","covers.py","platforms.py","publishing.py","research.py","browser.mjs","relay_llm.py","discovery.py","material_library.py","homefeed.py","share_page.py",
       "package.json","package-lock.json","requirements-cover.txt","requirements-media.txt","material_media.py",
       "launcher.py","启动界面.py","启动浏览器.py","file_picker.py","file_store.py","material_understanding.py","material_formats.py","project_workspaces.py",
       "部署与安装.md","README.md","打包项目.py","config/project.example.json","config/initial-leads.json",
       "references/browser.md","references/platforms.md","references/creator-buddy-evaluation.md","references/material-understanding-validation.md","references/legacy-plan-format.md")
TREES={"ui":{'.html','.css','.js'},"skills":{'.md'},"tests":{'.py','.cjs'}}


def build(output=None):
    stamp=datetime.now(timezone(timedelta(hours=8)))
    target=Path(output) if output else ROOT.parent/'交付包'/('operating_agent-'+stamp.strftime('%Y-%m-%d')+'.zip')
    paths=list(FILES)
    for folder,suffixes in TREES.items():
        paths.extend(p.relative_to(ROOT).as_posix() for p in sorted((ROOT/folder).rglob('*'))
                     if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    payload={name:(ROOT/name).read_bytes() for name in paths}
    payload['config/project.json']=payload['config/project.example.json']
    config=json.loads(payload['config/project.json'])
    if config['assets'] or config['project']['id']!='my-creative-project':
        raise ValueError('交付模板必须保持空白，不得带入项目素材')
    manifest={'format':1,'created_at':stamp.isoformat(timespec='seconds'),
              'edition':'空白项目源码包','runtime_data_included':False,
              'files':[{'path':name,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
                       for name,body in sorted(payload.items())]}
    payload['交付清单.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.zip.tmp')
    try:
        with ZipFile(temporary,'w',compression=ZIP_DEFLATED) as bundle:
            for name,body in sorted(payload.items()):bundle.writestr('operating_agent/'+name,body)
        with ZipFile(temporary) as bundle:
            if bundle.testzip():raise ValueError('ZIP完整性检查失败')
        temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='仅打包可交付源码与空白配置，不读取data')
    parser.add_argument('--output',help='输出ZIP路径')
    args=parser.parse_args()
    print(build(args.output).resolve())
