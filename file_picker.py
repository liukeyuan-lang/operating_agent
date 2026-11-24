"""Local OS file dialog; no upload and no change to the selected originals."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

_dialog_lock=threading.Lock()


def browse_directories(value=None,workspace=None):
    """List local folders for the in-page picker without changing filesystem state."""
    if value is not None and not isinstance(value,str):raise ValueError('目录位置格式无效')
    start=Path(value).expanduser() if value else Path(workspace or Path.cwd())
    try:path=start.resolve(strict=True)
    except (OSError,RuntimeError):raise ValueError('目录不存在或无法访问')
    if not path.is_dir():raise ValueError('请选择文件夹')
    try:
        directories=[]
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=True):continue
                    target=Path(entry.path).resolve(strict=True)
                except (OSError,RuntimeError):continue
                directories.append({'name':entry.name,'path':str(target)})
    except OSError as error:raise ValueError('无法读取这个目录：'+str(error))
    directories.sort(key=lambda row:(row['name'].startswith('.'),row['name'].casefold()))
    candidates=[('工作区',Path(workspace or Path.cwd())),('桌面',Path.home()/'Desktop'),
                ('文稿',Path.home()/'Documents'),('下载',Path.home()/'Downloads')]
    if sys.platform=='darwin':candidates.append(('外接磁盘',Path('/Volumes')))
    locations=[];seen=set()
    for name,candidate in candidates:
        try:target=candidate.resolve(strict=True)
        except (OSError,RuntimeError):continue
        if not target.is_dir() or str(target) in seen:continue
        seen.add(str(target));locations.append({'name':name,'path':str(target)})
    parent=path.parent
    return {'directory':str(path),'parent':str(parent) if parent!=path else None,
            'directories':directories,'locations':locations}


def _pick(directory=False):
    if not _dialog_lock.acquire(blocking=False):raise ValueError('已有文件选择窗口，请先完成或取消')
    try:
        process=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--directory' if directory else '--dialog'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:out,error=process.communicate()
        finally:
            if process.poll() is None:process.terminate();process.wait()
        if process.returncode:raise ValueError('无法打开文件选择窗口，请检查Python的Tk支持和本机桌面会话。'+error.strip()[-300:])
        paths=json.loads(out)
        if not isinstance(paths,list) or not all(isinstance(p,str) for p in paths):raise ValueError('文件选择结果格式无效')
        return paths
    finally:_dialog_lock.release()


def pick_files():return _pick()


def pick_directory():
    paths=_pick(directory=True)
    return paths[0] if paths else None


def dialog(directory=False):
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw()
    try:
        root.attributes('-topmost',True)
        if directory:
            value=filedialog.askdirectory(parent=root,title='选择整组素材所在目录',mustexist=True)
            paths=[value] if value else []
        else:paths=filedialog.askopenfilenames(parent=root,title='选择项目素材（MP4，可多选）',filetypes=[('MP4 视频','*.mp4')])
        print(json.dumps(list(paths),ensure_ascii=False),flush=True)
    finally:root.destroy()


if __name__=='__main__':
    try:dialog(directory='--directory' in sys.argv)
    except Exception as error:
        print(str(error),file=sys.stderr);sys.exit(1)
