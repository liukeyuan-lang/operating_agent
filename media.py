"""Read MP4 container metadata without moving or modifying original media."""
import hashlib
import struct
from pathlib import Path


def boxes(stream, start, end):
    while start+8 <= end:
        stream.seek(start)
        size, kind = struct.unpack(">I4s", stream.read(8))
        header = 8
        if size == 1:
            size = struct.unpack(">Q", stream.read(8))[0]
            header = 16
        elif size == 0:
            size = end-start
        if size < header or start+size > end:
            raise ValueError("MP4 容器结构无效")
        yield kind, start+header, start+size
        start += size


def _inspect_mp4(value):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("当前支持登记本地 MP4 成片")
    before = path.stat()
    tracks = []
    duration = None
    with path.open("rb") as stream:
        top = list(boxes(stream, 0, before.st_size))
        if not any(k == b"ftyp" for k, _, _ in top):
            raise ValueError("文件不是可识别的 MP4")
        for kind, start, end in top:
            if kind != b"moov":
                continue
            for kind, start, end in boxes(stream, start, end):
                if kind == b"mvhd":
                    stream.seek(start)
                    version = stream.read(1)[0]
                    stream.seek(start+(20 if version == 1 else 12))
                    scale = struct.unpack(">I", stream.read(4))[0]
                    ticks = struct.unpack(">Q" if version == 1 else ">I", stream.read(8 if version == 1 else 4))[0]
                    duration = round(ticks/scale, 3) if scale else None
                if kind != b"trak":
                    continue
                track = {}
                for sub, a, b in boxes(stream, start, end):
                    if sub == b"tkhd":
                        stream.seek(b-8)
                        width, height = struct.unpack(">II", stream.read(8))
                        track.update(width=round(width/65536), height=round(height/65536))
                    if sub == b"mdia":
                        for key, x, y in boxes(stream, a, b):
                            if key == b"hdlr":
                                stream.seek(x+8)
                                track["handler"] = stream.read(4).decode("ascii", "replace")
                tracks.append(track)
    video = next((t for t in tracks if t.get("handler") == "vide"), None)
    if not video:
        raise ValueError("MP4 未发现视频轨道")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("素材读取期间发生变化，请重新登记")
    return {"locator":str(path), "version":"sha256:"+digest,
            "availability":"local", "type":"video", "rights":"unknown", "published":None,
            "file_signature":{"size":after.st_size,"mtime_ns":after.st_mtime_ns},
            "specs":{"duration_seconds":duration, "width":video.get("width"), "height":video.get("height"),
                     "audio_track":any(t.get("handler") == "soun" for t in tracks), "container":"mp4"},
            "notes":"已读取容器元数据；未据此核实画面、音频版权或发布历史。"}


def inspect_mp4(value):
    try:
        return _inspect_mp4(value)
    except (struct.error,IndexError) as error:
        raise ValueError("MP4 元数据不完整，请检查成片文件") from error


def local_available(asset, version=None):
    if asset.get("availability") != "local" or version and asset.get("version") != version:
        return False
    try:
        path = Path(asset["locator"])
        stat = path.stat()
        signature = asset["file_signature"]
        return path.is_file() and stat.st_size == signature["size"] and stat.st_mtime_ns == signature["mtime_ns"]
    except (OSError, KeyError):
        return False
