"""Local conversion fixtures. No model calls or external document dependencies."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image

from material_formats import document_text,image_pages,prepared_document,MIMES
from material_understanding import scan_directory


def make_glb(path,document,bin_body=b'BIN-SECRET'):
    encoded=json.dumps(document,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    encoded+=b' '*((-len(encoded))%4);bin_body+=b'\0'*((-len(bin_body))%4)
    chunks=struct.pack('<II',len(encoded),0x4e4f534a)+encoded
    if bin_body:chunks+=struct.pack('<II',len(bin_body),0x004e4942)+bin_body
    path.write_bytes(struct.pack('<4sII',b'glTF',2,12+len(chunks))+chunks)
    return path


class MaterialFormatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def entry(self,path):
        return {'path':str(path),'relative_path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'mime':MIMES[path.suffix]}
    def archive(self,name,parts):
        path=self.root/name
        with ZipFile(path,'w') as z:
            for n,s in parts.items():z.writestr(n,s)
        return self.entry(path)

    def test_scan_accepts_new_extensions_but_does_not_silently_skip_unknown_files(self):
        names=['a.webp','a.tiff','a.mkv','a.webm','a.avi','a.m4a','a.flac','a.ogg','a.glb','a.md','a.csv','a.json','a.srt','a.docx','a.pptx','a.xlsx']
        for name in names:(self.root/name).write_bytes(b'fixture')
        self.assertEqual(len(scan_directory(str(self.root))['files']),len(names))
        (self.root/'old.doc').write_bytes(b'old-office')
        with self.assertRaisesRegex(ValueError,'DOCX'):scan_directory(str(self.root))

    def test_office_lock_files_are_ignored_before_hashing_or_extraction(self):
        valid=self.archive('资源.xlsx',{
            'xl/workbook.xml':'<workbook xmlns="urn:x" xmlns:r="urn:r"><sheets><sheet name="素材" r:id="sheet"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels':'<Relationships><Relationship Id="sheet" Target="worksheets/sheet1.xml"/></Relationships>',
            'xl/worksheets/sheet1.xml':'<worksheet xmlns="urn:x"><sheetData><row><c r="A1"><v>1</v></c></row></sheetData></worksheet>'})
        (self.root/'.~资源.xlsx').write_bytes(b'not-a-workbook')
        (self.root/'~$资源.xlsx').write_bytes(b'not-a-workbook-either')
        snapshot=scan_directory(str(self.root))
        self.assertEqual([row['relative_path'] for row in snapshot['files']],['资源.xlsx'])
        self.assertIn('工作表：素材',document_text(valid)[0])

    def test_glb_2_json_is_bounded_evidence_and_bin_and_uris_are_not_read(self):
        external='https://example.invalid/private-texture.png?token=never-send'
        document={'asset':{'version':'2.0','generator':'fixture'},'scene':0,
            'scenes':[{'name':'主场景','nodes':[0]}],
            'nodes':[{'name':'角色根节点','mesh':0,'skin':0,'camera':0,'translation':[1,2,3]}],
            'meshes':[{'name':'角色网格','primitives':[{'attributes':{'POSITION':0},'indices':1,'material':0}]}],
            'materials':[{'name':'红色材质','pbrMetallicRoughness':{'baseColorFactor':[1,0,0,1],'metallicFactor':.2}}],
            'animations':[{'name':'挥手','samplers':[{'input':2,'output':3,'interpolation':'LINEAR'}],
                           'channels':[{'sampler':0,'target':{'node':0,'path':'rotation'}}]}],
            'cameras':[{'name':'主相机','type':'perspective','perspective':{'yfov':.7,'znear':.1}}],
            'skins':[{'name':'骨骼','joints':[0],'inverseBindMatrices':4}],
            'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3','min':[0,0,0],'max':[1,1,1]}],
            'textures':[{'source':0}],'images':[{'name':'外部贴图','uri':external},{'name':'内嵌贴图','bufferView':1,'mimeType':'image/png'}],
            'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':16}],'buffers':[{'byteLength':16},{'byteLength':1,'uri':'secret.bin'}],
            'extensionsUsed':['KHR_materials_unlit']}
        path=make_glb(self.root/'角色.glb',document,b'BIN-SECRET-DO-NOT-SEND')
        entry=self.entry(path);original=path.read_bytes();text,notes=document_text(entry);evidence=json.loads(text)
        self.assertEqual(evidence['source']['container'],'GLB 2.0');self.assertEqual(evidence['source']['bin_chunks_skipped'],1)
        self.assertEqual(evidence['scenes'][0]['name'],'主场景');self.assertEqual(evidence['nodes'][0]['mesh'],0)
        self.assertEqual(evidence['meshes'][0]['primitives'][0]['attributes'],{'POSITION':0})
        self.assertEqual(evidence['materials'][0]['name'],'红色材质');self.assertEqual(evidence['animations'][0]['name'],'挥手')
        self.assertEqual(evidence['images'][0]['resource_source'],'external_uri_omitted')
        self.assertNotIn(external,text);self.assertNotIn('secret.bin',text);self.assertNotIn('BIN-SECRET',text)
        self.assertTrue(any('未上传GLB原文件' in note for note in notes))
        with prepared_document(entry,{'index':1,'text_start':0,'text_end':len(text)},(text,notes),self.root/'glb') as upload:
            self.assertEqual(upload['mime'],'text/plain');self.assertEqual(upload['preparation']['method'],'glb_json_evidence')
            self.assertEqual(Path(upload['path']).read_text(encoding='utf-8'),text)
        self.assertEqual(path.read_bytes(),original)

    def test_malformed_or_non_v2_glb_fails_locally(self):
        path=make_glb(self.root/'old.glb',{'asset':{'version':'2.0'}})
        body=bytearray(path.read_bytes());struct.pack_into('<I',body,4,1);path.write_bytes(body)
        with self.assertRaisesRegex(ValueError,'GLB 2.0'):document_text(self.entry(path))
        path=make_glb(self.root/'bad.glb',{'asset':{'version':'2.0'}})
        body=bytearray(path.read_bytes());struct.pack_into('<I',body,12,3);path.write_bytes(body)
        with self.assertRaisesRegex(ValueError,'4字节对齐'):document_text(self.entry(path))
        encoded=b'{"asset":{"version":"2.0"}}';encoded+=b' '*((-len(encoded))%4)
        chunks=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',0,0x004e4942)*1024
        path=self.root/'too-many.glb';path.write_bytes(struct.pack('<4sII',b'glTF',2,12+len(chunks))+chunks)
        with self.assertRaisesRegex(ValueError,'1024'):document_text(self.entry(path))

    def test_plain_text_encodings_and_office_text_are_converted_not_executed(self):
        for encoding in ['utf-8-sig','utf-16','gb18030']:
            path=self.root/'字幕.srt';path.write_bytes('中文字幕\n00:00:01 --> 00:00:02'.encode(encoding))
            self.assertIn('中文字幕',document_text(self.entry(path))[0])
        entry=self.archive('方案.docx',{'word/document.xml':'<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>项目正文</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格文字</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'})
        text=document_text(entry);self.assertEqual(text[0],'项目正文\n表格文字');self.assertIn('图片',text[1][0])
        original=Path(entry['path']).read_bytes()
        with prepared_document(entry,{'index':1,'text_start':0,'text_end':len(text[0])},text,self.root/'tmp') as upload:
            self.assertEqual(upload['mime'],'text/plain');self.assertIn('表格文字',Path(upload['path']).read_text(encoding='utf-8'))
        self.assertFalse(Path(upload['path']).exists());self.assertEqual(Path(entry['path']).read_bytes(),original)

    def test_presentation_follows_slide_order_not_filenames(self):
        entry=self.archive('演示.pptx',{
            'ppt/presentation.xml':'<p:presentation xmlns:p="urn:p" xmlns:r="urn:r"><p:sldIdLst><p:sldId r:id="two"/><p:sldId r:id="one"/></p:sldIdLst></p:presentation>',
            'ppt/_rels/presentation.xml.rels':'<Relationships><Relationship Id="two" Target="slides/slide2.xml"/><Relationship Id="one" Target="slides/slide1.xml"/></Relationships>',
            'ppt/slides/slide1.xml':'<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:p><a:r><a:t>第二页</a:t></a:r></a:p></p:sld>',
            'ppt/slides/slide2.xml':'<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:p><a:r><a:t>第一页</a:t></a:r></a:p></p:sld>'})
        text,notes=document_text(entry);self.assertLess(text.index('第一页'),text.index('第二页'));self.assertIn('动画',notes[0])

    def test_spreadsheet_shared_strings_inline_strings_and_formulas_keep_cell_identity(self):
        entry=self.archive('资源.xlsx',{
            'xl/workbook.xml':'<workbook xmlns="urn:x" xmlns:r="urn:r"><sheets><sheet name="素材台账" r:id="sheet"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels':'<Relationships><Relationship Id="sheet" Target="worksheets/sheet1.xml"/></Relationships>',
            'xl/sharedStrings.xml':'<sst xmlns="urn:x"><si><t>现金激励</t></si></sst>',
            'xl/worksheets/sheet1.xml':'<worksheet xmlns="urn:x"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>创作者</t></is></c><c r="C1"><f>1+2</f><v>3</v></c></row></sheetData></worksheet>'})
        text,notes=document_text(entry)
        for term in ['素材台账','A1\t现金激励','B1\t创作者','C1\t3 [公式：1+2]']:self.assertIn(term,text)
        self.assertIn('不计算公式',notes[0])

    def test_tiff_all_pages_and_bmp_conversion_keep_pixels_and_originals(self):
        path=self.root/'多页.tiff';Image.new('RGB',(12,10),'red').save(path,save_all=True,append_images=[Image.new('RGB',(12,10),'blue')])
        entry=self.entry(path);original=path.read_bytes();self.assertEqual(image_pages(entry),2)
        for i,colour in enumerate([(255,0,0),(0,0,255)]):
            with prepared_document(entry,{'index':i+1,'page_index':i},None,self.root/'pages') as upload:
                with Image.open(upload['path']) as converted:self.assertEqual(converted.getpixel((0,0)),colour)
            self.assertFalse(Path(upload['path']).exists())
        self.assertEqual(path.read_bytes(),original)
        path=self.root/'海报.bmp';Image.new('RGB',(10,10),'green').save(path)
        with prepared_document(self.entry(path),{'index':1,'page_index':0},None,self.root/'pages') as upload:
            self.assertEqual(upload['mime'],'image/png')

    def test_malformed_office_and_xml_entities_fail_before_any_network_work(self):
        for content in ['bad xml','<!DOCTYPE x [<!ENTITY a "hello">]><x/>']:
            entry=self.archive('坏文档.docx',{'word/document.xml':content})
            with self.assertRaises(ValueError):document_text(entry)
