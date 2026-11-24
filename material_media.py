"""Make accurate, temporary analysis clips; never modify the source media."""
from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import wave

from media import inspect_mp4

SEGMENT_SECONDS=300
INLINE_VIDEO_BYTES=12*1024*1024  # Local transport target; not a provider limit.


def video_compression_enabled():
    value=os.environ.get('MATERIAL_COMPRESS_VIDEO','0').strip().lower()
    if value not in {'0','1','false','true','off','on'}:raise ValueError('MATERIAL_COMPRESS_VIDEO需为0或1')
    return value in {'1','true','on'}


def ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError):
        binary=shutil.which('ffmpeg')
        if binary:return binary
        raise ValueError('读取或切分这份音视频需要FFmpeg；请运行 python -m pip install -r requirements-media.txt') from None


def duration_seconds(entry):
    path=Path(entry['path'])
    if path.suffix.lower()=='.mp4':
        try:
            value=inspect_mp4(path)['specs']['duration_seconds']
            if value and math.isfinite(value) and value>0:return value
        except ValueError:pass
    if path.suffix.lower()=='.wav':
        try:
            with wave.open(str(path),'rb') as stream:return stream.getnframes()/stream.getframerate()
        except (wave.Error,EOFError):pass
    result=subprocess.run([ffmpeg_path(),'-hide_banner','-i',str(path)],capture_output=True,timeout=60,
                          encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    match=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',result.stderr)
    if not match:raise ValueError('无法读取音视频时长，请检查文件是否完整：'+path.name)
    hours,minutes,seconds=map(float,match.groups());value=hours*3600+minutes*60+seconds
    if not math.isfinite(value) or value<=0:raise ValueError('音视频时长无效：'+path.name)
    return value


def part_max_bytes():
    try:value=int(os.environ.get('MATERIAL_PART_MAX_BYTES','18000000'))
    except ValueError:raise ValueError('MATERIAL_PART_MAX_BYTES须为正整数，最多20000000字节') from None
    if not 0<value<=20000000:raise ValueError('MATERIAL_PART_MAX_BYTES须为正整数，最多20000000字节')
    return value


def timed_media(entry):return entry['mime'].startswith(('video/','audio/')) or Path(entry['path']).suffix.lower()=='.gif'


def needs_transcode(entry):
    return timed_media(entry) and Path(entry['path']).suffix.lower() not in {'.mp4','.mp3','.wav'}


def ranges(duration,max_seconds=SEGMENT_SECONDS):
    if not math.isfinite(duration) or duration<=0:raise ValueError('音视频时长无效')
    if not math.isfinite(max_seconds) or max_seconds<=0:raise ValueError('切片时长无效')
    result=[];start=0
    while start<duration:
        end=min(start+max_seconds,duration)
        if duration-end<1e-6:end=duration
        result.append((start,end));start=end
    return result


def media_ranges(entry,duration):
    size=Path(entry['path']).stat().st_size
    span=min(SEGMENT_SECONDS,max(.25,duration*part_max_bytes()*.85/max(1,size))) if size>part_max_bytes() else SEGMENT_SECONDS
    return ranges(duration,span)


def assert_unchanged(entry):
    with Path(entry['path']).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=entry['sha256']:raise ValueError('处理期间素材发生变化，请重新选择目录：'+entry['relative_path'])


@contextmanager
def analysis_clip(entry,start,end,temporary_root):
    """Re-encode to cut at the requested times, rather than at keyframes."""
    assert_unchanged(entry)
    root=Path(temporary_root);root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='clip-',dir=root) as folder:
        video=entry['mime'].startswith('video/') or Path(entry['path']).suffix.lower()=='.gif'
        path=Path(folder)/('segment.mp4' if video else 'segment.mp3')
        command=[ffmpeg_path(),'-hide_banner','-loglevel','error','-nostdin','-y','-ss',str(start),'-i',entry['path'],
                 '-t',str(end-start)]
        command+=['-map','0:v:0','-map','0:a:0?','-sn','-dn','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-preset','veryfast','-crf','23',
                  '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart'] if video else ['-vn','-c:a','libmp3lame','-b:a','128k']
        command.append(str(path))
        try:
            result=subprocess.run(command,capture_output=True,timeout=900,encoding='utf-8',errors='replace',
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:raise ValueError('本地切片超时，原素材未改写：'+entry['relative_path']) from None
        if result.returncode or not path.is_file() or not path.stat().st_size:
            raise ValueError('音视频切片失败：'+entry['relative_path']+'；'+result.stderr[-500:])
        assert_unchanged(entry)
        body_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        yield {'path':str(path),'relative_path':f'{Path(entry["relative_path"]).stem}_{start:g}-{end:g}s'+path.suffix,
               'sha256':body_hash,'mime':'video/mp4' if video else 'audio/mp3','size':path.stat().st_size,
               'preparation':{'method':'timeline_clip','upload_bytes':path.stat().st_size,'start_seconds':start,'end_seconds':end,
                              'lossy_transcode':True,'limitations':['音视频切片经过转码，保留连续时间范围；视频保留首路画面与首路音轨，未分析其他轨道。']}}


@contextmanager
def upload_media(entry,duration,temporary_root):
    """Large video gets a smaller analysis copy; keep source, time and audio."""
    source=Path(entry['path'])
    if not video_compression_enabled() or not entry['mime'].startswith('video/') or source.stat().st_size<=INLINE_VIDEO_BYTES:
        yield entry;return
    if not duration or duration<=0:raise ValueError('无法确认大视频时长，未发送素材')
    assert_unchanged(entry)
    root=Path(temporary_root);root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='upload-',dir=root) as folder:
        path=Path(folder)/'analysis.mp4'
        scale="scale=w='trunc(iw*min(1,1920/max(iw,ih))/2)*2':h='trunc(ih*min(1,1920/max(iw,ih))/2)*2'"
        prefix=[ffmpeg_path(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(source),
                '-map','0:v:0','-map','0:a:0?','-sn','-dn','-vf',scale,'-c:v','libx264','-preset','veryfast',
                '-pix_fmt','yuv420p','-c:a','aac','-b:a','96000','-movflags','+faststart']
        video_rate=max(64000,int(INLINE_VIDEO_BYTES*.85*8/duration)-96000)
        settings=[['-crf','23'],['-b:v',str(video_rate),'-maxrate',str(video_rate),'-bufsize',str(video_rate*2)]]
        for options in settings:
            try:
                result=subprocess.run(prefix+options+[str(path)],capture_output=True,timeout=900,encoding='utf-8',errors='replace',
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired:raise ValueError('生成分析副本超时，原视频未改写') from None
            if result.returncode or not path.is_file() or not path.stat().st_size:
                raise ValueError('生成分析副本失败：'+entry['relative_path']+'；'+result.stderr[-500:])
            if path.stat().st_size<=INLINE_VIDEO_BYTES:break
        if path.stat().st_size>INLINE_VIDEO_BYTES:raise ValueError('分析副本仍然过大，未再次发送；请使用较低码率的视频副本')
        assert_unchanged(entry)
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        yield {'path':str(path),'relative_path':Path(entry['relative_path']).stem+'-分析版.mp4','sha256':digest,
               'mime':'video/mp4','size':path.stat().st_size,
               'preparation':{'method':'compressed_video','original_bytes':source.stat().st_size,'upload_bytes':path.stat().st_size,
                              'duration_seconds':duration,'max_side':1920,'audio':'first original audio track, AAC'}}
