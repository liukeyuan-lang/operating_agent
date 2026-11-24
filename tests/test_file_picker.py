"""File selection and atomic project/material registration, with synthetic files."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import file_picker
from demo import Files,add_assets,make_server,public_state,request_run
from test_planning import mp4
from workflow import project


class FilePickerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.files=Files(self.root/'state.json');self.video=mp4(self.root/'合成素材.mp4')
    def tearDown(self):self.tmp.cleanup()
    def test_picker_runs_current_python_and_preserves_unicode_filename(self):
        process=Mock();process.communicate.return_value=(json.dumps([str(self.video)],ensure_ascii=False),'');process.returncode=0;process.poll.return_value=0
        with patch.object(file_picker.subprocess,'Popen',return_value=process) as launch:
            self.assertEqual(file_picker.pick_files(),[str(self.video)])
            self.assertEqual(launch.call_args.args[0][0],file_picker.sys.executable)
            self.assertNotIn('shell',launch.call_args.kwargs)
    def test_in_page_directory_browser_is_read_only_and_lists_quick_locations(self):
        workspace=self.root/'工作区';workspace.mkdir();child=workspace/'子目录';child.mkdir();(workspace/'不是目录.txt').write_text('x')
        result=file_picker.browse_directories(str(workspace),workspace)
        self.assertEqual(result['directory'],str(workspace.resolve()))
        self.assertEqual(result['directories'],[{'name':'子目录','path':str(child.resolve())}])
        self.assertEqual(result['locations'][0],{'name':'工作区','path':str(workspace.resolve())})
        self.assertTrue((workspace/'不是目录.txt').is_file())
        with self.assertRaisesRegex(ValueError,'文件夹'):file_picker.browse_directories(str(workspace/'不是目录.txt'),workspace)
        with self.assertRaisesRegex(ValueError,'格式'):file_picker.browse_directories([],workspace)
    def test_file_selection_is_cancelable_and_never_registers_until_submitted(self):
        server=make_server(self.files,0);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/state') as response:state=json.load(response)
            def post(payload,token=None):
                headers={'Content-Type':'application/json'}
                if token:headers['X-Demo-Token']=token
                return urlopen(Request(base+'/api/assets/pick',data=json.dumps(payload).encode(),headers=headers))
            with patch('demo.pick_files',return_value=[]) as picker:
                with self.assertRaises(HTTPError):post({})
                picker.assert_not_called()
                with post({},state['csrf']) as response:self.assertEqual(json.load(response),{'files':[]})
            browse=Request(base+'/api/materials/browse',data=json.dumps({'directory':str(self.root)}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':state['csrf']})
            with urlopen(browse) as response:self.assertEqual(json.load(response)['directory'],str(self.root.resolve()))
            foreign=Request(base+'/api/materials/browse',data=b'{}',headers={'Content-Type':'application/json','X-Demo-Token':state['csrf'],'Origin':'https://example.test'})
            with self.assertRaises(HTTPError) as blocked:urlopen(foreign)
            self.assertEqual(blocked.exception.code,403)
            with patch('demo.pick_files',return_value=[str(self.video)]):
                with post({},state['csrf']) as response:
                    selected=json.load(response)['files'];self.assertEqual(selected[0]['name'],self.video.name)
            self.assertFalse(self.files.path.exists())
        finally:server.shutdown();server.server_close();worker.join()
    def test_new_exploration_ignores_legacy_material_fields_without_reading_files(self):
        before=hashlib.sha256(self.video.read_bytes()).hexdigest()
        req=request_run(self.files,{'mode':'new','name':'全新项目','direction':'合成方向','assets_brief':'','asset_paths':[str(self.video)],'auto_verify':True})
        self.assertEqual(req['profile_snapshot']['asset_references'],[])
        self.assertNotIn('materials',req['profile_snapshot'])
        self.assertEqual(req['status'],'waiting_codex')
        self.assertEqual(project(self.files.load())['asset_references'],[])
        self.assertEqual(hashlib.sha256(self.video.read_bytes()).hexdigest(),before)
    def test_failed_media_read_does_not_create_half_project_or_half_batch(self):
        bad=self.root/'损坏.mp4';bad.write_text('invalid')
        with self.assertRaises(ValueError):request_run(self.files,{'mode':'new','exploration_requirements':''})
        self.assertFalse(self.files.path.exists())
        with self.assertRaises(ValueError):add_assets(self.files,{'paths':[str(self.video),str(bad)]})
        self.assertFalse(self.files.path.exists())
    def test_batch_registration_is_scoped_and_deduplicates_same_file(self):
        add_assets(self.files,{'paths':[str(self.video),str(self.video)]})
        self.assertEqual(len(public_state(self.files)['assets']),1)
        request_run(self.files,{'mode':'new','name':'另一个项目','direction':'合成','assets_brief':'暂无素材'})
        self.assertEqual(public_state(self.files)['assets'],[])


if __name__=='__main__':unittest.main()
