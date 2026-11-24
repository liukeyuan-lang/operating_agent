"""Deterministic cover production from a creator-provided video, without rewriting it."""
import hashlib
import subprocess
from pathlib import Path

from media import local_available


def font_path():
    candidates=[Path("C:/Windows/Fonts/msyh.ttc"),Path("C:/Windows/Fonts/simhei.ttf"),
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/STHeiti Light.ttc"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
    path=next((p for p in candidates if p.is_file()),None)
    if not path:raise ValueError("本机缺少中文字体，封面尚未生成")
    return path


def make_cover(asset, directory, seconds, headline, subtitle, project_name,height=1440):
    if not local_available(asset):raise ValueError("素材文件已变化或不可用，请重新登记")
    duration=asset.get("specs",{}).get("duration_seconds")
    if type(seconds) not in {int,float} or not duration or not 0<=seconds<duration:
        raise ValueError("封面取帧时间需位于原片时长内")
    if not isinstance(headline,str) or not headline.strip() or len(headline.replace("\n",""))>24:
        raise ValueError("封面主标题请控制在24字内")
    if not isinstance(subtitle,str) or len(subtitle)>40:raise ValueError("封面副标题过长")
    try:
        import imageio_ffmpeg
        from PIL import Image,ImageDraw,ImageFont,ImageOps
    except ImportError as error:
        raise ValueError("封面生成需要本机已有的 Pillow 与 imageio-ffmpeg；未生成图片") from error
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    frame=directory/"source-frame.png"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-nostdin","-hide_banner","-loglevel","error","-y",
                    "-ss",str(seconds),"-i",asset["locator"],"-frames:v","1","-an",str(frame)],
                   check=True,capture_output=True,timeout=30,
                   creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if not local_available(asset):raise ValueError("取帧时原片发生变化，请重新登记")
    font_file=str(font_path())
    def font(size):return ImageFont.truetype(font_file,size)
    canvas=Image.new("RGB",(1080,height),"#ebece3")
    draw=ImageDraw.Draw(canvas)
    ink="#243c36";muted="#687d72";accent="#b66c47"
    draw.line((60,88,1020,88),fill=ink,width=2)
    draw.text((60,110),"C430 / PROJECT ARCHIVE",font=font(28),fill=ink)
    draw.text((60,170),"动画 PV  /  WORLD BUILDING",font=font(22),fill=muted)
    # Wrap by actual glyph width instead of cropping art or guessing Chinese character width.
    lines=[]
    for paragraph in headline.splitlines():
        line=""
        for char in paragraph:
            if line and draw.textlength(line+char,font=font(76))>950:
                lines.append(line);line=char
            else:line+=char
        lines.append(line)
    if len(lines)>3:raise ValueError("封面主标题超过排版范围，请缩短")
    for n,line in enumerate(lines):draw.text((60,240+n*104),line,font=font(76),fill=ink)
    # Keep the entire original frame. The portrait canvas does not turn the PV into a vertical edit.
    with Image.open(frame) as source:
        picture=ImageOps.contain(source.convert("RGB"),(960,580))
        y=round(height*602/1440)+(580-picture.height)//2
        canvas.paste(picture,((1080-picture.width)//2,y))
    bottom=height-1440
    draw.line((60,1214+bottom,1020,1214+bottom),fill=muted,width=1)
    size=30
    while size>16 and draw.textlength(subtitle,font=font(size))>950:size-=1
    draw.text((60,1240+bottom),subtitle,font=font(size),fill=ink)
    size=28
    while size>12 and draw.textlength(project_name,font=font(size))>950:size-=1
    draw.text((60,1300+bottom),project_name,font=font(size),fill=muted)
    draw.text((60,1360+bottom),"C430 AI STUDIO",font=font(20),fill=muted)
    draw.ellipse((990,1355+bottom,1010,1375+bottom),fill=accent)
    output=directory/"cover.png";canvas.save(output,"PNG")
    return {"path":str(output.resolve()),"sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
            "frame_path":str(frame.resolve()),"frame_seconds":seconds,"headline":headline,"subtitle":subtitle,
            "width":1080,"height":height,"format":"png","asset_version":asset["version"],
            "production":"原片截帧与确定性排版；保留整幅画面，未改写或重剪原片"}
