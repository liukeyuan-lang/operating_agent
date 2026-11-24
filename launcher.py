"""Portable foreground launchers; no shell strings, installation or background jobs."""
import argparse
import getpass
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def python_path(root=ROOT,system=None,env=None):
    env=os.environ if env is None else env
    explicit=env.get('OPPORTUNITY_PYTHON')
    if explicit:
        path=Path(explicit).expanduser()
        if not path.is_file():raise ValueError('OPPORTUNITY_PYTHON需指向Python可执行文件的完整路径')
        return str(path.resolve())
    system=system or os.name
    candidate=Path(root)/('.venv/Scripts/python.exe' if system=='nt' else '.venv/bin/python')
    return str(candidate.resolve()) if candidate.is_file() else sys.executable


def run(command,env,root=ROOT):
    try:
        process=subprocess.Popen(command,cwd=root,env=env)
        try:return process.wait()
        except KeyboardInterrupt:
            # A terminal Ctrl+C reaches the child too; allow its own cleanup first.
            try:return process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            return 130
    except OSError as error:
        print('启动失败：'+str(error),file=sys.stderr)
        return 1


def launch(kind,args):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    try:
        interpreter=python_path()
        env={**os.environ,'OPPORTUNITY_PYTHON':interpreter,'PYTHONUTF8':'1'}
        if kind=='ui':
            parser=argparse.ArgumentParser(description='启动本地创作工作台（Windows / macOS / Linux）')
            parser.add_argument('--port',type=int,default=8765)
            parser.add_argument('--ask-key',action='store_true',help='输入素材理解用的中转站密钥，仅保存在本次服务进程中')
            parser.add_argument('--material-timeout',type=float,help='素材请求的网络超时秒数，默认600；不自动重试')
            parser.add_argument('--compress-videos',action=argparse.BooleanOptionalAction,default=None,
                                help='开启或关闭大视频额外压缩，默认关闭；超过5分钟的切片规则不变')
            options=parser.parse_args(args)
            if options.compress_videos is not None:env['MATERIAL_COMPRESS_VIDEO']='1' if options.compress_videos else '0'
            if options.material_timeout is not None:
                if not math.isfinite(options.material_timeout) or options.material_timeout<=0:raise ValueError('--material-timeout须为正数（秒）')
                env['MATERIAL_REQUEST_TIMEOUT_SECONDS']=str(options.material_timeout)
            if options.ask_key:env['RELAY_API_KEY']=getpass.getpass('素材理解API key（不回显、不保存）：')
            if not 1024<=options.port<=65535:raise ValueError('端口须为1024–65535')
            print(f'探索机会：http://127.0.0.1:{options.port}/explore\n准备发布：http://127.0.0.1:{options.port}/publish\n保持终端开启，按Ctrl+C停止。',flush=True)
            command=[interpreter,'-X','utf8',str(ROOT/'demo.py'),'serve','--port',str(options.port)]
        else:
            node=shutil.which('node')
            if not node:raise ValueError('未找到Node.js，请按部署与安装.md安装并重新打开终端')
            command=[node,str(ROOT/'browser.mjs'),*(args or ['serve'])]
        return run(command,env)
    except ValueError as error:
        print('启动失败：'+str(error),file=sys.stderr)
        return 1
