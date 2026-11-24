"""Group content cache, deduplication, scope and HTTP flow; synthetic files only."""
import base64
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from demo import Files,create_publishing_project,make_server,public_state,request_run,start_run
import material_understanding as material
import material_media
from material_understanding import MaterialService,scan_directory,messages_for,parse_description,parse_summary
from test_planning import mp4
from workflow import profile_digest,project


def make_glb(path):
    document={'asset':{'version':'2.0','generator':'integration fixture'},'scene':0,
              'scenes':[{'name':'测试场景','nodes':[0]}],'nodes':[{'name':'测试节点','mesh':0}],
              'meshes':[{'name':'测试网格','primitives':[]}],'buffers':[{'byteLength':1024}]}
    encoded=json.dumps(document,ensure_ascii=False,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4)
    binary=b'RAW-GLB-BINARY-MUST-NOT-BE-SENT'+b'\0'*1024;binary+=b'\0'*((-len(binary))%4)
    chunks=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
    path.write_bytes(struct.pack('<4sII',b'glTF',2,12+len(chunks))+chunks);return path


class FakeGemini:
    def __init__(self):self.calls=0;self.gate=None;self.fail=False;self.messages=[];self.history=[];self.fail_calls=set()
    def chat(self,messages,model,max_tokens,stream=False,on_progress=None):
        self.calls+=1;self.messages=copy.deepcopy(messages);self.history.append(copy.deepcopy(messages))
        assert model=='gemini-3.8-flash'
        if self.gate:self.gate.wait(timeout=5)
        if self.fail or self.calls in self.fail_calls:raise ValueError('合成网络错误，不是真实请求')
        ids=[c['text'].split('；')[0].removeprefix('file_id=') for c in messages[0]['content'] if c.get('text','').startswith('file_id=')]
        value={'title':'合成素材项目','description':'隔离测试的素材描述，不代表真实作品。','themes':['合成主题'],'styles':['测试风格'],
            'files':[{'file_id':i,'description':'合成文件说明','uncertainties':['权属未知']} for i in set(ids)],'uncertainties':['发布历史未知']}
        return {'text':json.dumps(value,ensure_ascii=False),'model':model,'usage':{'total_tokens':123}}


class MaterialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.directory=self.root/'素材目录';self.directory.mkdir();(self.directory/'说明.txt').write_text('合成素材一',encoding='utf-8')
        self.client=FakeGemini();self.service=MaterialService(self.root/'data/materials.json',lambda:self.client)
        self.files=Files(self.root/'data/workspace.json')
    def tearDown(self):self.service.pool.shutdown(wait=True);self.tmp.cleanup()
    def complete(self,directory=None):
        job=self.service.start(str(directory or self.directory));self.service.futures.get(job['id'],DummyFuture()).result(timeout=8)
        result=self.service.status(job['id']);self.assertEqual(result['status'],'complete',result.get('error'));return result
    def binding(self,job):return {'material_directory':str(self.directory),'material_analysis_id':job['id']}
    def test_network_timeout_can_be_extended_without_enabling_compression(self):
        with patch.dict(os.environ,{'RELAY_API_KEY':'fixture-not-a-real-key'},clear=True):
            self.assertEqual(MaterialService._client().timeout,600)
            self.assertFalse(material_media.video_compression_enabled())
            with patch.dict(os.environ,{'MATERIAL_REQUEST_TIMEOUT_SECONDS':'1200'}):
                self.assertEqual(MaterialService._client().timeout,1200)
            for invalid in ['0','-1','nan','inf','bad']:
                with patch.dict(os.environ,{'MATERIAL_REQUEST_TIMEOUT_SECONDS':invalid}):
                    with self.assertRaisesRegex(ValueError,'正数'):MaterialService._client()

    def test_live_request_progress_is_persisted_with_current_file_and_summary_context(self):
        (self.directory/'第二份.txt').write_text('另一份测试素材',encoding='utf-8')
        observed=[];base_chat=self.client.chat
        def streaming(*args,on_progress=None,**kwargs):
            for phase in ['uploading','waiting_response','receiving']:
                on_progress({'phase':phase,'request_bytes':1234,'uploaded_bytes':1000,'received_characters':12})
                current=self.service.load()['analyses'][0]
                self.assertEqual(current['status'],'running')
                observed.append(copy.deepcopy(current['progress']))
            return base_chat(*args,**kwargs)
        self.client.chat=streaming
        result=self.complete()
        self.assertEqual(len(observed),9)
        self.assertTrue(all(p['file_name'] and p['segment_index']==1 for p in observed[:6]))
        self.assertTrue(all(p['stage']=='group_summary' and not p['file_name'] for p in observed[6:]))
        self.assertNotIn('request',result['progress']);self.assertEqual(result['progress']['files_complete'],2)

    def test_interrupted_upload_retains_progress_and_cached_record_does_not_resend(self):
        from relay_llm import RelayError
        def interrupted(*args,on_progress=None,**kwargs):
            self.client.calls+=1
            on_progress({'phase':'uploading','request_bytes':1000,'uploaded_bytes':400})
            raise RelayError('合成上传中断',execution_unknown=True)
        self.client.chat=interrupted
        job=self.service.start(str(self.directory));self.service.futures[job['id']].result(timeout=8)
        result=self.service.status(job['id'])
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['progress']['request']['uploaded_bytes'],400)
        self.service.start(str(self.directory));self.assertEqual(self.client.calls,1)
    def test_empty_publishing_workspace_can_render_without_persisting_placeholder(self):
        state=public_state(self.files,'publishing')
        self.assertEqual(state['projects'],[])
        self.assertEqual(state['current_project']['id'],'__empty_publishing__')
        self.assertEqual(state['publications'],[])
        self.assertFalse(self.files.path.exists())
    def test_same_group_reused_across_paths_and_after_restart_without_new_call(self):
        first=self.complete();other=self.root/'复制目录';shutil.copytree(self.directory,other)
        copied=self.service.start(str(other))
        self.assertEqual(copied['id'],first['id']);self.assertTrue(copied['cached']);self.assertEqual(self.client.calls,1)
        restart=MaterialService(self.service.path,lambda:(_ for _ in ()).throw(AssertionError('不应调用模型')))
        try:self.assertTrue(restart.start(str(self.directory))['cached'])
        finally:restart.close()
        catalog=self.service.load();self.assertEqual(len(catalog['directories']),2);self.assertEqual(len(catalog['analyses']),1)
        self.assertIn('合成素材项目',(self.root/'data/素材目录与理解.csv').read_text(encoding='utf-8-sig'))
    def test_content_change_with_same_size_and_timestamp_invalidates_cache(self):
        first=self.complete();path=self.directory/'说明.txt';before=path.stat()
        path.write_text('合成素材二',encoding='utf-8');os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        second=self.complete();self.assertNotEqual(second['fingerprint'],first['fingerprint']);self.assertEqual(self.client.calls,2)
        with self.assertRaisesRegex(ValueError,'变化'):self.service.bind(str(self.directory),first['id'])
        with patch.object(material,'PROMPT_VERSION','new-version'),patch.object(material,'FILE_PROMPT_VERSION','new-file-version'):self.complete()
        self.assertEqual(self.client.calls,3)

    def test_files_are_sent_separately_and_adding_one_reuses_existing_file(self):
        (self.directory/'海报.png').write_bytes(b'synthetic-image')
        first=self.complete();self.assertEqual(self.client.calls,3)  # Two files plus text-only group synthesis.
        self.assertEqual([sum(c['type']=='file' for c in m[0]['content']) for m in self.client.history],[1,1,0])
        self.assertEqual(len(first['description']['files']),2)
        (self.directory/'补充.txt').write_text('新增素材',encoding='utf-8')
        second=self.complete();self.assertEqual(self.client.calls,5)
        self.assertEqual(sum(f.get('reused',False) for f in second['file_results']),2)
        self.assertEqual(len(self.service.load()['file_analyses']),3)
        self.assertTrue((self.root/'data/素材文件理解.csv').exists())

    def test_glb_runs_through_normal_cache_path_without_sending_raw_container(self):
        (self.directory/'说明.txt').unlink();source=make_glb(self.directory/'角色.glb');digest=hashlib.sha256(source.read_bytes()).hexdigest()
        first=self.complete();self.assertEqual(first['file_results'][0]['status'],'complete');self.assertEqual(self.client.calls,1)
        payload=self.client.history[0];block=next(c['file'] for c in payload[0]['content'] if c['type']=='file')
        uploaded=base64.b64decode(block['file_data'].split(',',1)[1]);self.assertTrue(uploaded.lstrip().startswith(b'{'))
        self.assertNotIn(b'glTF',uploaded);self.assertNotIn(b'RAW-GLB-BINARY-MUST-NOT-BE-SENT',uploaded)
        evidence=json.loads(uploaded);self.assertEqual(evidence['scenes'][0]['name'],'测试场景')
        record=self.service.load()['file_analyses'][0];piece=record['segments'][0]
        self.assertEqual(record['file_id'],digest);self.assertEqual(piece['input_preparation']['method'],'glb_json_evidence')
        self.assertTrue(any('未上传GLB原文件' in value for value in first['description']['uncertainties']))
        cached=self.service.start(str(self.directory));self.assertTrue(cached['cached']);self.assertEqual(self.client.calls,1)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)

    def test_different_groups_share_inflight_file_without_duplicate_model_calls(self):
        other=self.root/'另一组';shutil.copytree(self.directory,other);(other/'新增.txt').write_text('另一份内容',encoding='utf-8')
        self.client.gate=threading.Event()
        try:
            first=self.service.start(str(self.directory));second=self.service.start(str(other))
        finally:self.client.gate.set()
        for job in [first,second]:
            self.service.futures[job['id']].result(timeout=8)
            self.assertEqual(self.service.status(job['id'])['status'],'complete')
        self.assertEqual(self.client.calls,3)

    def test_directory_is_not_limited_to_32_files_or_64_mib(self):
        for i in range(33):(self.directory/f'{i}.txt').write_text(str(i),encoding='utf-8')
        with (self.directory/'大文件.txt').open('wb') as stream:stream.truncate(65*1024*1024)
        snapshot=scan_directory(str(self.directory))
        self.assertEqual(len(snapshot['files']),35);self.assertGreater(snapshot['total_bytes'],64*1024*1024)

    def test_legacy_completed_group_and_file_descriptions_are_reused(self):
        job=self.complete();data=self.service.load();data['analyses'][0]['prompt_version']='materials-v1';data['file_analyses']=[];self.service._save(data)
        restart=MaterialService(self.service.path,lambda:self.client)
        try:
            self.assertTrue(restart.start(str(self.directory))['cached']);restart.bind(str(self.directory),job['id'])
            (self.directory/'新增.txt').write_text('新内容',encoding='utf-8')
            request=restart.start(str(self.directory));restart.futures[request['id']].result(timeout=8)
            self.assertEqual(restart.status(request['id'])['status'],'complete')
            self.assertEqual(self.client.calls,3)
            self.assertTrue(any(r.get('method')=='legacy_group_evidence' for r in restart.load()['file_analyses']))
        finally:restart.pool.shutdown(wait=True)

    def test_long_video_failure_resumes_only_unfinished_segments_after_restart(self):
        (self.directory/'说明.txt').unlink();source=mp4(self.directory/'长视频.mp4');original=source.read_bytes()
        clips=[]
        @contextmanager
        def fake_clip(entry,start,end,temporary_root):
            clips.append((start,end));path=self.root/'temporary-clip.mp4';body=f'synthetic-{start}-{end}'.encode();path.write_bytes(body)
            try:yield {'path':str(path),'relative_path':path.name,'sha256':material.hashlib.sha256(body).hexdigest(),'mime':'video/mp4'}
            finally:path.unlink()
        self.client.fail_calls={2}
        with patch.object(material,'duration_seconds',return_value=601),patch.object(material,'analysis_clip',side_effect=fake_clip):
            job=self.service.start(str(self.directory));self.service.futures[job['id']].result(timeout=8)
            self.assertEqual(self.service.status(job['id'])['status'],'failed')
            self.assertEqual(self.client.calls,2);self.service.start(str(self.directory));self.assertEqual(self.client.calls,2)
            restart=MaterialService(self.service.path,lambda:self.client)
            try:
                retried=restart.start(str(self.directory),retry=True);restart.futures[retried['id']].result(timeout=8)
                result=restart.status(job['id']);self.assertEqual(result['status'],'complete',result.get('error'))
                self.assertEqual(self.client.calls,5)
                self.assertEqual(clips,[(0,300),(300,600),(300,600),(600,601)])
                self.assertEqual([(s['start_seconds'],s['end_seconds']) for s in result['file_results'][0]['segments']],[(0,300),(300,600),(600,601)])
                self.assertEqual(result['progress']['files_complete'],1)
                self.assertIn('600',json.dumps(self.client.history[-1],ensure_ascii=False))
                self.assertTrue(all(c['type']=='text' for c in self.client.history[-1][0]['content']))
            finally:restart.pool.shutdown(wait=True)
        self.assertEqual(source.read_bytes(),original);self.assertFalse((self.root/'temporary-clip.mp4').exists())

    def test_five_minute_boundary_and_tail_segment(self):
        self.assertEqual(material_media.ranges(300),[(0,300)])
        self.assertEqual(material_media.ranges(300.5),[(0,300),(300,300.5)])
        self.assertEqual(material_media.ranges(660),[(0,300),(300,600),(600,660)])

    def test_size_based_video_splitting_checks_real_outputs_before_sending_and_resumes(self):
        (self.directory/'说明.txt').unlink();source=self.directory/'高码率.mp4';source.write_bytes(b'v'*200)
        original=source.read_bytes();clips=[]
        @contextmanager
        def fake_clip(entry,start,end,temporary_root):
            clips.append((start,end));body=b'x'*max(1,int((end-start)*40));path=self.root/'clip.mp4';path.write_bytes(body)
            try:yield {'path':str(path),'relative_path':'clip.mp4','sha256':material.hashlib.sha256(body).hexdigest(),'mime':'video/mp4','size':len(body)}
            finally:path.unlink()
        self.client.fail_calls={2}
        with patch.dict(os.environ,{'MATERIAL_PART_MAX_BYTES':'100','MATERIAL_COMPRESS_VIDEO':'0'}),patch.object(material,'duration_seconds',return_value=10),patch.object(material,'analysis_clip',side_effect=fake_clip):
            job=self.service.start(str(self.directory));self.service.futures[job['id']].result(timeout=8)
            first=self.service.status(job['id']);self.assertEqual(first['status'],'failed')
            prefix=self.service.load()['file_analyses'][0]['segments'][0]['completed_at']
            self.assertEqual(self.client.calls,2)
            self.service.start(str(self.directory));self.assertEqual(self.client.calls,2)
            job=self.service.start(str(self.directory),retry=True);self.service.futures[job['id']].result(timeout=8)
        result=self.service.status(job['id']);self.assertEqual(result['status'],'complete',result.get('error'))
        row=self.service.load()['file_analyses'][0];segments=row['segments']
        self.assertEqual(segments[0]['completed_at'],prefix);self.assertEqual(segments[0]['start_seconds'],0);self.assertEqual(segments[-1]['end_seconds'],10)
        self.assertTrue(all(a['end_seconds']==b['start_seconds'] for a,b in zip(segments,segments[1:])))
        self.assertTrue(row['retired_segments']);self.assertTrue(all(s['input_preparation']['upload_bytes']<=100 for s in segments))
        for messages in self.client.history:
            for c in messages[0]['content']:
                if c['type']=='file':self.assertLessEqual(len(base64.b64decode(c['file']['file_data'].split(',',1)[1])),100)
        self.assertEqual(source.read_bytes(),original)

    def test_retry_old_413_adopts_smaller_segments_without_changing_cache_version(self):
        from relay_llm import RelayError
        (self.directory/'说明.txt').unlink();source=self.directory/'旧失败.mp4';source.write_bytes(b'v'*200)
        base=self.client.chat
        def rejected(*args,**kwargs):raise RelayError('HTTP 413: base64 is too large, maximum: 30MB')
        self.client.chat=rejected
        with patch.object(material,'duration_seconds',return_value=10):
            job=self.service.start(str(self.directory));self.service.futures[job['id']].result(timeout=8)
        self.assertEqual(len(self.service.load()['file_analyses'][0]['segments']),1)
        self.client.chat=base
        @contextmanager
        def fake_clip(entry,start,end,temporary_root):
            path=self.root/'clip.mp4';body=b'chunk';path.write_bytes(body)
            try:yield {'path':str(path),'relative_path':'clip.mp4','sha256':material.hashlib.sha256(body).hexdigest(),'mime':'video/mp4'}
            finally:path.unlink()
        with patch.dict(os.environ,{'MATERIAL_PART_MAX_BYTES':'100'}),patch.object(material,'analysis_clip',side_effect=fake_clip):
            job=self.service.start(str(self.directory),retry=True);self.service.futures[job['id']].result(timeout=8)
        self.assertEqual(self.service.status(job['id'])['status'],'complete')
        row=self.service.load()['file_analyses'][0]
        self.assertGreater(len(row['segments']),1);self.assertIn('413',row['retired_segments'][0]['error'])

    def test_long_text_uses_all_chunks_and_tiff_uses_all_pages(self):
        from PIL import Image
        (self.directory/'说明.txt').write_text('abcdefghijk',encoding='utf-8')
        with patch.object(material,'TEXT_CHARS',5):job=self.complete()
        row=self.service.load()['file_analyses'][0]
        self.assertEqual([(p['text_start'],p['text_end']) for p in row['segments']],[(0,5),(5,10),(10,11)])
        self.assertEqual(''.join(base64.b64decode(m[0]['content'][-1]['file']['file_data'].split(',',1)[1]).decode('utf-8') for m in self.client.history[:3]),'abcdefghijk')
        (self.directory/'说明.txt').unlink();Image.new('RGB',(10,10),'red').save(self.directory/'两页.tif',save_all=True,append_images=[Image.new('RGB',(10,10),'blue')])
        result=self.complete();self.assertEqual(len(result['file_results'][0]['segments']),2)

    def test_office_extraction_limitations_are_saved_even_if_model_omits_them(self):
        from zipfile import ZipFile
        (self.directory/'说明.txt').unlink()
        with ZipFile(self.directory/'方案.docx','w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="urn:w"><w:p><w:r><w:t>项目文字说明</w:t></w:r></w:p></w:document>')
        result=self.complete();detail=result['description']['files'][0]
        self.assertTrue(any('未读取内嵌图片' in s for s in detail['uncertainties']))
        self.assertTrue(any('未读取内嵌图片' in s for s in result['description']['uncertainties']))
        self.assertEqual(result['description']['files'][0]['file_id'],scan_directory(str(self.directory))['files'][0]['sha256'])

    def test_retry_old_unsegmented_text_adopts_character_ranges(self):
        (self.directory/'说明.txt').write_text('abcdefghijk',encoding='utf-8');first=self.complete()
        data=self.service.load();data['analyses'][0].update(status='failed',error='旧请求失败')
        row=data['file_analyses'][0];row.update(status='failed',error='旧请求失败')
        piece=row['segments'][0];piece.update(status='failed',error='旧请求失败')
        for field in ['kind','text_start','text_end']:piece.pop(field,None)
        self.service._save(data)
        with patch.object(material,'TEXT_CHARS',4):
            job=self.service.start(str(self.directory),retry=True);self.service.futures[job['id']].result(timeout=8)
        self.assertEqual(self.service.status(job['id'])['status'],'complete')
        row=self.service.load()['file_analyses'][0]
        self.assertEqual([(p['text_start'],p['text_end']) for p in row['segments']],[(0,4),(4,8),(8,11)])
        self.assertEqual(row['retired_segments'][0]['error'],'旧请求失败')

    def test_summary_binds_source_files_without_trusting_model_echoed_chunk_ids(self):
        original={'sha256':'original','relative_path':'视频.mp4'}
        part={'start_seconds':0,'end_seconds':300,'analysis':{'title':'切片','description':'蓝色画面',
              'files':[{'file_id':'clip-id','description':'蓝色画面','uncertainties':['用途未知']}]}}
        response=json.dumps({'title':'视频总结','description':'前蓝后红','files':[{'file_id':'clip-id','description':'错误归属'}]})
        result=parse_summary(response,{'files':[original]},[part])
        self.assertEqual(result['files'][0]['file_id'],'original')
        self.assertEqual(result['files'][0]['description'],'前蓝后红')
        payload=material.summary_messages({'files':[original]},[part],'文件汇总')
        self.assertNotIn('clip-id',json.dumps(payload,ensure_ascii=False))

    def test_group_summary_keeps_verified_individual_descriptions(self):
        rows=[{'sha256':'a','relative_path':'甲.txt'},{'sha256':'b','relative_path':'乙.txt'}]
        parts=[{'file_id':r['sha256'],'analysis':{'title':'文件','description':'描述',
                'files':[{'file_id':r['sha256'],'description':r['relative_path']+'内容','uncertainties':['作者未知']}]}} for r in rows]
        result=parse_summary(json.dumps({'title':'整体','description':'整组总结','files':[]}),{'files':rows},parts)
        self.assertEqual([r['description'] for r in result['files']],['甲.txt内容','乙.txt内容'])
        self.assertEqual(result['files'][0]['uncertainties'],['作者未知'])

    def test_compressed_upload_is_bound_to_original_file_not_derivative_hash(self):
        (self.directory/'说明.txt').unlink();source=mp4(self.directory/'原片.mp4')
        original_hash=material.hashlib.sha256(source.read_bytes()).hexdigest()
        @contextmanager
        def derivative(entry,duration,temporary_root):
            path=self.root/'analysis.mp4';path.write_bytes(b'synthetic-derivative')
            try:yield {'path':str(path),'relative_path':path.name,'sha256':material.hashlib.sha256(path.read_bytes()).hexdigest(),
                       'mime':'video/mp4','size':path.stat().st_size,'preparation':{'method':'compressed_video'}}
            finally:path.unlink()
        with patch.object(material,'upload_media',side_effect=derivative):result=self.complete()
        self.assertEqual(result['description']['files'][0]['file_id'],original_hash)
        (self.directory/'新增.txt').write_text('新文件',encoding='utf-8')
        combined=self.complete();self.assertEqual(len(combined['description']['files']),2)
        self.assertEqual(self.client.calls,3)  # Original was understood once, then one new file and summary.
    def test_parallel_requests_share_one_model_call(self):
        self.client.gate=threading.Event()
        try:
            first=self.service.start(str(self.directory))
            second=self.service.start(str(self.directory))
            self.assertEqual(first['id'],second['id'])
        finally:self.client.gate.set()
        self.service.futures[first['id']].result(timeout=8)
        self.assertEqual(self.client.calls,1)
    def test_failure_is_visible_not_auto_retried_and_explicit_retry_can_recover(self):
        self.client.fail=True;job=self.service.start(str(self.directory));self.service.futures[job['id']].result(timeout=8)
        self.assertEqual(self.service.status(job['id'])['status'],'failed')
        self.service.start(str(self.directory));self.assertEqual(self.client.calls,1)
        self.client.fail=False;retried=self.service.start(str(self.directory),retry=True);self.service.futures[retried['id']].result(timeout=8)
        self.assertEqual(self.service.status(job['id'])['status'],'complete');self.assertEqual(self.client.calls,2)
        row=self.service.load()['file_analyses'][0]
        self.assertIn('合成网络错误',row['failure_history'][0]['error'])
        self.assertIn('合成网络错误',row['segments'][0]['failure_history'][0]['error'])
    def test_incomplete_old_worker_does_not_silently_call_again(self):
        job=self.complete();data=self.service.load();data['analyses'][0]['status']='running';self.service._save(data)
        restart=MaterialService(self.service.path,lambda:self.client)
        try:self.assertEqual(restart.start(str(self.directory))['status'],'unknown')
        finally:restart.close()
        self.assertEqual(self.client.calls,1)
    def test_file_payload_contains_actual_bytes_and_all_files_must_be_described(self):
        snap=scan_directory(str(self.directory));messages=messages_for(snap)
        block=next(c['file'] for c in messages[0]['content'] if c['type']=='file')
        self.assertEqual(base64.b64decode(block['file_data'].split(',')[1]),(self.directory/'说明.txt').read_bytes())
        self.assertNotIn(str(self.root),messages[0]['content'][0]['text'])
        with self.assertRaisesRegex(ValueError,'全部文件'):
            parse_description(json.dumps({'title':'测试','description':'测试','files':[]}),snap)
        (self.directory/'密钥.env').write_text('never-send')
        with self.assertRaisesRegex(ValueError,'不支持'):scan_directory(str(self.directory))
    def test_publish_name_and_description_default_to_model_or_respect_user_values(self):
        job=self.complete();first=create_publishing_project(self.files,self.binding(job),self.service)
        self.assertEqual(first['name'],'合成素材项目');self.assertTrue(first['auto_fields']['name'])
        second=create_publishing_project(self.files,{**self.binding(job),'name':'自定名称','description':'自定描述'},self.service)
        self.assertEqual((second['name'],second['direction']),('自定名称','自定描述'))
        self.assertFalse(second['auto_fields']['description']);self.assertEqual(self.client.calls,1)
        self.assertEqual(public_state(self.files)['publications'],[])
        self.assertEqual(public_state(self.files,'publishing',first['id'])['material_understanding']['id'],job['id'])
    def test_exploration_never_requires_or_binds_materials_and_continuation_keeps_same_profile(self):
        payload={'mode':'new','name':'合成探索','direction':'互动艺术','understanding_required':True}
        request=request_run(self.files,payload,self.service)
        self.assertEqual(self.client.calls,0)
        self.assertNotIn('materials',request['profile_snapshot'])
        self.assertEqual(request['profile_snapshot']['asset_references'],[])
        pid=request['project_id'];digest=profile_digest(project(self.files.load()))
        request_run(self.files,{'mode':'continue','project_id':pid},self.service)
        self.assertEqual(profile_digest(project(self.files.load())),digest)
        (self.directory/'说明.txt').write_text('素材已变更')
        self.assertEqual(start_run(self.files,request_id=request['id'])['scenario'],'opportunity_discovery')
        self.assertEqual(self.client.calls,0)


class DummyFuture:
    def result(self,timeout=None):return None


class WorkspaceHTTPTest(unittest.TestCase):
    def test_two_pages_understand_once_and_projects_jobs_media_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'素材';directory.mkdir();video=mp4(directory/'合成视频.mp4')
            files=Files(root/'data/workspace.json');client=FakeGemini()
            server=make_server(files,0,lambda:client);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def get(path):
                try:
                    with urlopen(base+path,timeout=5) as response:return json.load(response)
                except HTTPError as error:
                    self.fail(f'{path}: HTTP {error.code}: {error.read().decode("utf-8")}')
            csrf=get('/api/state')['csrf']
            def post(path,payload,token=True):
                headers={'Content-Type':'application/json'}
                if token:headers['X-Demo-Token']=csrf
                with urlopen(Request(base+path,data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers),timeout=5) as response:return json.load(response)
            try:
                for path,required in [('/','/homefeed.js'),('/explore','session-form'),('/publish','publishing-project-form')]:
                    with urlopen(base+path) as response:self.assertIn(required,response.read().decode())
                with urlopen(base+'/publish') as response:
                    html=response.read().decode();self.assertNotIn('id="request-form"',html);self.assertNotIn('data-tab="opportunities"',html)
                with self.assertRaises(HTTPError):post('/api/materials/analyze',{'directory':str(directory)},token=False)
                with patch('demo.pick_directory',return_value=None):self.assertEqual(post('/api/materials/pick',{}),{'directory':None})
                self.assertFalse(files.path.exists())
                job=post('/api/materials/analyze',{'directory':str(directory)})
                for attempt in range(100):
                    result=get('/api/materials/status?id='+job['id'])
                    if result['status'] not in {'queued','running'}:break
                    time.sleep(.02)
                self.assertEqual(result['status'],'complete',result.get('error'))
                binding={'material_directory':str(directory),'material_analysis_id':job['id']}
                explore=post('/api/exploration/requests',{'mode':'new','name':'探索甲','direction':'合成方向',**binding})
                pub=post('/api/publishing/projects',binding)
                self.assertEqual(pub['name'],'合成素材项目')
                cached=post('/api/materials/analyze',{'directory':str(directory)})
                self.assertTrue(cached['cached']);self.assertEqual(cached['id'],job['id']);self.assertEqual(client.calls,1)
                pubstate=get('/api/state?workspace=publishing')
                self.assertEqual(pubstate['current_project']['id'],pub['id'])
                self.assertEqual(get('/api/state')['current_project']['id'],explore['project_id'])
                self.assertEqual({p['workspace'] for p in pubstate['projects']},{'publishing'})
                asset=pubstate['assets'][0]
                created=post('/api/publications',{'workspace':'publishing','project_id':pub['id'],'asset_id':asset['id']})
                post('/api/publications/edit',{'workspace':'publishing','project_id':pub['id'],'id':created['id'],'expected_revision':1,'title':'发布标题','body':'合成正文'})
                self.assertEqual(get('/api/state?workspace=publishing')['publications'][0]['current']['title'],'发布标题')
                self.assertEqual(get('/api/state')['publications'],[])
                self.assertEqual(files.load()['active_project_id'],explore['project_id'])
                with urlopen(base+'/api/media/'+asset['id']+'?workspace=publishing&project_id='+pub['id']) as response:self.assertEqual(response.read(),video.read_bytes())
                with self.assertRaises(HTTPError):urlopen(base+'/api/media/'+asset['id'])
                with self.assertRaises(HTTPError):post('/api/publications/edit',{'workspace':'publishing','project_id':explore['project_id'],'id':created['id'],'expected_revision':2,'title':'不能跨空间改'})
            finally:server.shutdown();server.server_close();worker.join()
