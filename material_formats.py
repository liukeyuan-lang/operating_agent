"""Local material adapters. Never execute document code, formulas or linked content."""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile,BadZipFile

MIMES={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp',
       '.bmp':'image/bmp','.tif':'image/tiff','.tiff':'image/tiff','.gif':'image/gif',
       '.mp4':'video/mp4','.mov':'video/mov','.m4v':'video/mp4','.webm':'video/webm',
       '.mkv':'video/x-matroska','.avi':'video/x-msvideo','.mpg':'video/mpeg','.mpeg':'video/mpeg',
       '.3gp':'video/3gpp','.flv':'video/x-flv','.wmv':'video/x-ms-wmv','.ts':'video/mp2t',
       '.mp3':'audio/mp3','.wav':'audio/wav','.m4a':'audio/mp4','.aac':'audio/aac',
       '.flac':'audio/flac','.ogg':'audio/ogg','.opus':'audio/ogg','.aif':'audio/aiff','.aiff':'audio/aiff','.wma':'audio/x-ms-wma',
       '.glb':'model/gltf-binary',
       '.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
       '.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
       '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
TEXT_EXTENSIONS={'.txt','.md','.markdown','.csv','.tsv','.json','.yaml','.yml','.srt','.vtt','.log','.xml','.html','.htm'}
MIMES.update({suffix:'text/plain' for suffix in TEXT_EXTENSIONS})
TEXT_CHARS=60000
GLB_JSON_MAX_BYTES=32*1024*1024
GLB_SAMPLE_ITEMS=32


def _short(value,limit=200):
    return value[:limit] if isinstance(value,str) else None


def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def _index(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None


def _numbers(value,limit=32):
    if not isinstance(value,list):return None
    result=[]
    for item in value[:limit]:
        number=_number(item)
        if number is None:return None
        result.append(number)
    return result


def _indices(value,limit=32):
    if not isinstance(value,list):return None
    result=[]
    for item in value[:limit]:
        number=_index(item)
        if number is None:return None
        result.append(number)
    return result


def _put(target,key,value):
    if value is not None:target[key]=value


def _extensions(value):
    return sorted(str(k)[:200] for k in value)[:32] if isinstance(value,dict) else None


def _texture_info(value):
    if not isinstance(value,dict):return None
    result={}
    for key in ('index','texCoord'):_put(result,key,_index(value.get(key)))
    for key in ('scale','strength'):_put(result,key,_number(value.get(key)))
    _put(result,'extensions',_extensions(value.get('extensions')))
    return result or None


def _named(index,value):
    result={'index':index}
    if isinstance(value,dict):
        _put(result,'name',_short(value.get('name')))
        _put(result,'extensions',_extensions(value.get('extensions')))
    return result


def _resource_source(value):
    """Describe URI placement without exposing or opening a local/remote URI."""
    if not isinstance(value,dict) or 'uri' not in value:return 'embedded_or_unspecified'
    uri=value.get('uri')
    return 'data_uri_omitted' if isinstance(uri,str) and uri.lower().startswith('data:') else 'external_uri_omitted'


def _read_exact(stream,length,message):
    body=stream.read(length)
    if len(body)!=length:raise ValueError(message)
    return body


def _glb_chunks(path):
    size=path.stat().st_size
    if size<20:raise ValueError('GLB文件过短')
    with path.open('rb') as stream:
        magic,version,declared=struct.unpack('<4sII',_read_exact(stream,12,'GLB文件头不完整'))
        if magic!=b'glTF':raise ValueError('GLB文件头无效')
        if version!=2:raise ValueError('仅支持GLB 2.0，当前容器版本为'+str(version))
        if declared!=size:raise ValueError('GLB声明长度与文件大小不一致')
        chunks=[];position=12;document=None
        while position<declared:
            if len(chunks)>=1024:raise ValueError('GLB分块数超过1024个本地解析上限')
            if declared-position<8:raise ValueError('GLB分块头不完整')
            chunk_length,chunk_type=struct.unpack('<II',_read_exact(stream,8,'GLB分块头不完整'));position+=8
            if chunk_length%4:raise ValueError('GLB分块长度未按4字节对齐')
            if chunk_length>declared-position:raise ValueError('GLB分块长度越界')
            chunks.append({'type':chunk_type,'bytes':chunk_length})
            if len(chunks)==1:
                if chunk_type!=0x4e4f534a:raise ValueError('GLB首个分块必须是JSON')
                if chunk_length>GLB_JSON_MAX_BYTES:raise ValueError('GLB JSON分块超过32MiB本地解析上限')
                raw=_read_exact(stream,chunk_length,'GLB JSON分块不完整')
                try:
                    document=json.loads(raw.rstrip(b'\x20\x00').decode('utf-8'),parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
                except (UnicodeDecodeError,json.JSONDecodeError,ValueError,RecursionError):
                    raise ValueError('GLB JSON分块无法解析') from None
            else:stream.seek(chunk_length,1)  # Skip BIN and unknown chunks without reading their bytes.
            position+=chunk_length
        if not isinstance(document,dict):raise ValueError('GLB JSON顶层必须是对象')
        return document,chunks


def _sample(values,convert):
    return [convert(i,v) for i,v in enumerate(values[:GLB_SAMPLE_ITEMS])] if isinstance(values,list) else []


def glb_text(entry):
    """Return bounded structural evidence from a GLB JSON chunk; never read BIN or URIs."""
    path=Path(entry['path'])
    try:document,chunks=_glb_chunks(path)
    except OSError as error:raise ValueError('无法读取GLB：'+path.name+'；'+str(error)[:300]) from None
    asset=document.get('asset')
    if not isinstance(asset,dict) or asset.get('version')!='2.0':raise ValueError('GLB JSON缺少 asset.version=2.0')
    keys=('scenes','nodes','meshes','materials','animations','cameras','skins','accessors','textures','images','samplers','bufferViews','buffers')
    counts={key:len(document.get(key,[])) for key in keys if isinstance(document.get(key),list)}
    evidence={'evidence_format':'bounded_glb_2_json_summary',
              'source':{'container':'GLB 2.0','source_bytes':path.stat().st_size,
                        'json_chunk_bytes':chunks[0]['bytes'],'bin_chunks_skipped':sum(c['type']==0x004e4942 for c in chunks),
                        'bin_bytes_skipped':sum(c['bytes'] for c in chunks if c['type']==0x004e4942)},
              'asset':{'version':'2.0'},'counts':counts,
              'sampling':{'maximum_items_per_section':GLB_SAMPLE_ITEMS,
                          'omitted_counts':{key:max(0,value-GLB_SAMPLE_ITEMS) for key,value in counts.items() if value>GLB_SAMPLE_ITEMS}},
              'extensions_used':[_short(v) for v in document.get('extensionsUsed',[])[:32] if isinstance(v,str)],
              'extensions_required':[_short(v) for v in document.get('extensionsRequired',[])[:32] if isinstance(v,str)]}
    for key in ('generator','copyright','minVersion'):_put(evidence['asset'],key,_short(asset.get(key)))
    _put(evidence['asset'],'extensions',_extensions(asset.get('extensions')))
    _put(evidence,'default_scene',_index(document.get('scene')))

    def scene(i,value):
        row=_named(i,value)
        if isinstance(value,dict):_put(row,'nodes',_indices(value.get('nodes')))
        return row
    evidence['scenes']=_sample(document.get('scenes'),scene)

    def node(i,value):
        row=_named(i,value)
        if not isinstance(value,dict):return row
        for key in ('mesh','skin','camera'):_put(row,key,_index(value.get(key)))
        _put(row,'children',_indices(value.get('children')))
        for key in ('translation','rotation','scale','matrix','weights'):_put(row,key,_numbers(value.get(key)))
        return row
    evidence['nodes']=_sample(document.get('nodes'),node)

    def mesh(i,value):
        row=_named(i,value)
        if not isinstance(value,dict):return row
        _put(row,'weights',_numbers(value.get('weights')))
        primitives=[]
        for primitive in value.get('primitives',[])[:8] if isinstance(value.get('primitives'),list) else []:
            if not isinstance(primitive,dict):continue
            item={};attributes=primitive.get('attributes')
            if isinstance(attributes,dict):item['attributes']={str(k)[:100]:v for k,v in list(attributes.items())[:32] if _index(v) is not None}
            for key in ('indices','material','mode'):_put(item,key,_index(primitive.get(key)))
            targets=primitive.get('targets')
            if isinstance(targets,list):item['targets']=[{str(k)[:100]:v for k,v in list(target.items())[:16] if _index(v) is not None} for target in targets[:8] if isinstance(target,dict)]
            _put(item,'extensions',_extensions(primitive.get('extensions')));primitives.append(item)
        row['primitive_count']=len(value.get('primitives',[])) if isinstance(value.get('primitives'),list) else 0
        row['primitives']=primitives
        return row
    evidence['meshes']=_sample(document.get('meshes'),mesh)

    def material(i,value):
        row=_named(i,value)
        if not isinstance(value,dict):return row
        pbr=value.get('pbrMetallicRoughness');summary={}
        if isinstance(pbr,dict):
            _put(summary,'baseColorFactor',_numbers(pbr.get('baseColorFactor')))
            for key in ('metallicFactor','roughnessFactor'):_put(summary,key,_number(pbr.get(key)))
            for key in ('baseColorTexture','metallicRoughnessTexture'):_put(summary,key,_texture_info(pbr.get(key)))
        if summary:row['pbrMetallicRoughness']=summary
        for key in ('normalTexture','occlusionTexture','emissiveTexture'):_put(row,key,_texture_info(value.get(key)))
        _put(row,'emissiveFactor',_numbers(value.get('emissiveFactor')))
        _put(row,'alphaMode',_short(value.get('alphaMode')));_put(row,'alphaCutoff',_number(value.get('alphaCutoff')))
        if isinstance(value.get('doubleSided'),bool):row['doubleSided']=value['doubleSided']
        return row
    evidence['materials']=_sample(document.get('materials'),material)

    def animation(i,value):
        row=_named(i,value)
        if not isinstance(value,dict):return row
        samplers=[]
        for sampler in value.get('samplers',[])[:GLB_SAMPLE_ITEMS] if isinstance(value.get('samplers'),list) else []:
            item={}
            if isinstance(sampler,dict):
                for key in ('input','output'):_put(item,key,_index(sampler.get(key)))
                _put(item,'interpolation',_short(sampler.get('interpolation')))
            samplers.append(item)
        channels=[]
        for channel in value.get('channels',[])[:GLB_SAMPLE_ITEMS] if isinstance(value.get('channels'),list) else []:
            if not isinstance(channel,dict):continue
            item={};_put(item,'sampler',_index(channel.get('sampler')));target=channel.get('target');target_summary={}
            if isinstance(target,dict):
                _put(target_summary,'node',_index(target.get('node')));_put(target_summary,'path',_short(target.get('path')))
                _put(target_summary,'extensions',_extensions(target.get('extensions')))
            if target_summary:item['target']=target_summary
            channels.append(item)
        row.update(sampler_count=len(value.get('samplers',[])) if isinstance(value.get('samplers'),list) else 0,samplers=samplers,
                   channel_count=len(value.get('channels',[])) if isinstance(value.get('channels'),list) else 0,channels=channels)
        return row
    evidence['animations']=_sample(document.get('animations'),animation)

    def camera(i,value):
        row=_named(i,value)
        if not isinstance(value,dict):return row
        _put(row,'type',_short(value.get('type')))
        for kind in ('perspective','orthographic'):
            source=value.get(kind);summary={}
            if isinstance(source,dict):
                for key in ('aspectRatio','yfov','zfar','znear','xmag','ymag'):_put(summary,key,_number(source.get(key)))
            if summary:row[kind]=summary
        return row
    evidence['cameras']=_sample(document.get('cameras'),camera)

    def skin(i,value):
        row=_named(i,value)
        if isinstance(value,dict):
            _put(row,'inverseBindMatrices',_index(value.get('inverseBindMatrices')));_put(row,'skeleton',_index(value.get('skeleton')))
            _put(row,'joints',_indices(value.get('joints')))
        return row
    evidence['skins']=_sample(document.get('skins'),skin)

    def accessor(i,value):
        row=_named(i,value)
        if not isinstance(value,dict):return row
        for key in ('bufferView','byteOffset','componentType','count'):_put(row,key,_index(value.get(key)))
        _put(row,'type',_short(value.get('type')));_put(row,'min',_numbers(value.get('min')));_put(row,'max',_numbers(value.get('max')))
        if isinstance(value.get('normalized'),bool):row['normalized']=value['normalized']
        sparse=value.get('sparse')
        if isinstance(sparse,dict):_put(row,'sparse_count',_index(sparse.get('count')))
        return row
    evidence['accessors']=_sample(document.get('accessors'),accessor)

    def texture(i,value):
        row=_named(i,value)
        if isinstance(value,dict):
            _put(row,'sampler',_index(value.get('sampler')));_put(row,'source',_index(value.get('source')))
        return row
    evidence['textures']=_sample(document.get('textures'),texture)

    def image(i,value):
        row=_named(i,value)
        if isinstance(value,dict):
            _put(row,'mimeType',_short(value.get('mimeType')));_put(row,'bufferView',_index(value.get('bufferView')))
            row['resource_source']=_resource_source(value)
        return row
    evidence['images']=_sample(document.get('images'),image)

    def sampler(i,value):
        row=_named(i,value)
        if isinstance(value,dict):
            for key in ('magFilter','minFilter','wrapS','wrapT'):_put(row,key,_index(value.get(key)))
        return row
    evidence['samplers']=_sample(document.get('samplers'),sampler)

    def buffer_view(i,value):
        row=_named(i,value)
        if isinstance(value,dict):
            for key in ('buffer','byteOffset','byteLength','byteStride','target'):_put(row,key,_index(value.get(key)))
        return row
    evidence['bufferViews']=_sample(document.get('bufferViews'),buffer_view)

    def buffer(i,value):
        row=_named(i,value)
        if isinstance(value,dict):
            _put(row,'byteLength',_index(value.get('byteLength')));row['resource_source']=_resource_source(value)
        return row
    evidence['buffers']=_sample(document.get('buffers'),buffer)
    text=json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False)
    if len(text)>240000:raise ValueError('GLB结构摘要超过本地安全上限')
    limitations=['仅在本机读取GLB 2.0的JSON分块并提取有界结构摘要；未上传GLB原文件，未读取BIN分块、顶点/纹理二进制或任何外部URI，因此不能判断实际外观、贴图内容与动画播放效果。']
    if any(value>GLB_SAMPLE_ITEMS for value in counts.values()):limitations.append('结构条目过多时每类仅提供前32项，counts与omitted_counts保留总数及省略数，不声称已展开全部条目。')
    return text,limitations


def _xml(archive,name):
    body=archive.read(name)
    if b'<!DOCTYPE' in body or b'<!ENTITY' in body:raise ValueError('文档包含不支持的XML实体声明')
    return ET.fromstring(body)


def _texts(node):return ''.join(e.text or '' for e in node.iter() if e.tag.rsplit('}',1)[-1]=='t')


def document_text(entry):
    """Return text and honest extraction limitations, or None for visual media."""
    path=Path(entry['path']);suffix=path.suffix.lower()
    if suffix=='.glb':
        try:return glb_text(entry)
        except ValueError as error:raise ValueError('无法读取GLB：'+path.name+'；'+str(error)[:300]) from None
    if suffix in TEXT_EXTENSIONS:
        raw=path.read_bytes()
        if raw.startswith((b'\xff\xfe',b'\xfe\xff')):text=raw.decode('utf-16')
        else:
            try:text=raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                try:text=raw.decode('gb18030')
                except UnicodeDecodeError:raise ValueError('文本编码无法识别，请另存为UTF-8：'+path.name) from None
        if not text.strip():raise ValueError('文本内容为空：'+path.name)
        return text,['HTML仅按源码文字读取，不执行脚本、不渲染或访问链接。'] if suffix in {'.html','.htm'} else []
    if suffix not in {'.docx','.pptx','.xlsx'}:return None
    try:
        with ZipFile(path) as archive:
            if len(archive.infolist())>10000 or sum(i.file_size for i in archive.infolist())>128*1024*1024:
                raise ValueError('Office文档解压后过大，请拆分或导出PDF')
            if suffix=='.docx':
                root=_xml(archive,'word/document.xml')
                text='\n'.join(_texts(p) for p in root.iter() if p.tag.endswith('}p'))
                notes=['仅提取正文与表格中的文字；未读取内嵌图片、图表、批注或完整排版。需要图文理解请导出PDF。']
            elif suffix=='.pptx':
                # Follow the presentation relationship order rather than sorting filenames.
                rels={r.attrib['Id']:r.attrib['Target'] for r in _xml(archive,'ppt/_rels/presentation.xml.rels')}
                sections=[]
                for i,slide in enumerate(e for e in _xml(archive,'ppt/presentation.xml').iter() if e.tag.endswith('}sldId')):
                    target=rels[next(v for k,v in slide.attrib.items() if k.endswith('}id'))]
                    name=target.lstrip('/') if target.startswith('/') else 'ppt/'+target
                    node=_xml(archive,name)
                    sections.append('幻灯片 '+str(i+1)+'\n'+'\n'.join(_texts(p) for p in node.iter() if p.tag.endswith('}p')))
                text='\n\n'.join(sections)
                notes=['仅提取各页文字，未读取图片、图表、动画、讲者备注或完整排版。需要视觉理解请导出PDF。']
            else:
                shared=[_texts(e) for e in _xml(archive,'xl/sharedStrings.xml')] if 'xl/sharedStrings.xml' in archive.namelist() else []
                rels={r.attrib['Id']:r.attrib['Target'] for r in _xml(archive,'xl/_rels/workbook.xml.rels')}
                sections=[]
                for sheet in (e for e in _xml(archive,'xl/workbook.xml').iter() if e.tag.endswith('}sheet')):
                    target=rels[next(v for k,v in sheet.attrib.items() if k.endswith('}id'))]
                    name=target.lstrip('/') if target.startswith('/') else 'xl/'+target
                    lines=['工作表：'+sheet.attrib.get('name','')]
                    for cell in (e for e in _xml(archive,name).iter() if e.tag.endswith('}c')):
                        children={e.tag.rsplit('}',1)[-1]:e for e in cell};value=children.get('v')
                        value=value.text or '' if value is not None else ''
                        if cell.attrib.get('t')=='s':value=shared[int(value)]
                        elif cell.attrib.get('t')=='inlineStr':value=_texts(cell)
                        if 'f' in children:value+=' [公式：'+(children['f'].text or '')+']'
                        if value:lines.append(cell.attrib.get('r','')+'\t'+value)
                    sections.append('\n'.join(lines))
                text='\n\n'.join(sections)
                notes=['仅提取工作表名称、单元格现有值与公式文本；不计算公式，不读取图表、图片或外部链接。']
    except (BadZipFile,KeyError,ET.ParseError,IndexError,StopIteration,ValueError) as error:
        raise ValueError('无法读取Office文档：'+path.name+'；'+str(error)[:300]) from None
    if not text.strip():raise ValueError('文档没有可提取文字，请导出PDF后理解：'+path.name)
    return text,notes


def image_pages(entry):
    if Path(entry['path']).suffix.lower() not in {'.bmp','.tif','.tiff','.webp'}:return 1
    try:
        from PIL import Image
    except ImportError:raise ValueError('读取BMP/TIFF/WebP需要Pillow，请安装requirements-media.txt') from None
    with Image.open(entry['path']) as image:
        if image.format=='WEBP' and getattr(image,'is_animated',False):
            raise ValueError('动态WebP请先转换为MP4；不会只取首帧冒充完整理解')
        return getattr(image,'n_frames',1)


@contextmanager
def prepared_document(entry,piece,text,temporary_root):
    """Convert text/Office and BMP/TIFF locally; preserve source and page identity."""
    suffix=Path(entry['path']).suffix.lower()
    if text is None and suffix not in {'.bmp','.tif','.tiff'}:yield entry;return
    root=Path(temporary_root);root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='document-',dir=root) as folder:
        if text is not None:
            path=Path(folder)/'content.txt'
            path.write_text(text[0][piece.get('text_start',0):piece.get('text_end',len(text[0]))],encoding='utf-8',newline='')
            mime='text/plain';notes=text[1];method='glb_json_evidence' if suffix=='.glb' else 'extracted_text'
        else:
            from PIL import Image,ImageOps
            path=Path(folder)/'page.png'
            with Image.open(entry['path']) as image:
                image.seek(piece.get('page_index',0));page=ImageOps.exif_transpose(image)
                page.convert('RGBA' if 'A' in page.getbands() else 'RGB').save(path)
            mime='image/png';notes=[];method='image_page'
        body=path.read_bytes()
        yield {'path':str(path),'relative_path':entry['relative_path']+f' (部分{piece["index"]})',
               'sha256':hashlib.sha256(body).hexdigest(),'mime':mime,'size':len(body),
               'preparation':{'method':method,'upload_bytes':len(body),'limitations':notes}}
