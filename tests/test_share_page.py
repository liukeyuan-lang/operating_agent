"""Offline sharing boundaries: project scope, escaping, download, and no runtime dependencies."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

import homefeed as h
import share_page
from demo import Files,make_server
from test_homefeed import note


class Elements(HTMLParser):
    def __init__(self):super().__init__();self.rows=[]
    def handle_starttag(self,tag,attrs):self.rows.append((tag,dict(attrs)))


class SharePageTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.files=h.FeedFiles(self.root/'homepage.json')
        self.session=h.create_session(self.files,{'mode':'new','name':'同事分享项目','login_confirmed':True})
        h.task(self.files,self.session['id'],True)
        h.record(self.files,{'session_id':self.session['id'],'packet_id':'share-fixture','notes':[note()]})
        self.view=h.notebook(self.files.load(),[])
    def tearDown(self):self.tmp.cleanup()
    def test_offline_page_keeps_cards_details_evidence_and_inline_styles(self):
        body=share_page.render(self.view,'2026-11-21T20:00:00+08:00')
        parser=Elements();parser.feed(body)
        self.assertIn('同事分享项目',body);self.assertIn('合成计划',body)
        self.assertIn('用户偏好',body);self.assertIn('2026-11-21T20:00:00+08:00',body)
        self.assertTrue(any(tag=='details' for tag,attrs in parser.rows))
        self.assertTrue(any(tag=='style' for tag,attrs in parser.rows))
        self.assertFalse(any(tag in {'script','iframe','form','input','button','img','link'} for tag,attrs in parser.rows))
        self.assertFalse(any('src' in attrs for tag,attrs in parser.rows))
        self.assertNotIn('/api/',body)
        policy=next(attrs['content'] for tag,attrs in parser.rows if tag=='meta' and attrs.get('http-equiv')=='Content-Security-Policy')
        self.assertEqual(policy,share_page.content_security_policy())
    def test_only_selected_project_candidates_and_no_private_app_state(self):
        view=copy.deepcopy(self.view)
        foreign=copy.deepcopy(view['opportunities'][0]);foreign.update(project_id='other-project',title='不应分享的另一项目机会')
        view['opportunities'].append(foreign)
        view['projects'].append({'name':'不应分享的其他项目名称'})
        view['current_project'].update(preferences='私有偏好原文不应整段导出',material_pack_ids=['private-pack'])
        view.update(csrf='private-csrf',execution_prompt='private-execution-prompt',llm={'api_key':'private-model-key'},
                    material_packs=[{'directory':'D:/private/materials','understanding':'private-material-understanding'}])
        body=share_page.render(view)
        for forbidden in ['不应分享的另一项目机会','不应分享的其他项目名称','私有偏好原文不应整段导出',
                          'private-pack','private-csrf','private-execution-prompt','private-model-key',
                          'D:/private/materials','private-material-understanding']:
            self.assertNotIn(forbidden,body)
    def test_untrusted_text_and_links_cannot_create_executable_markup(self):
        view=copy.deepcopy(self.view)
        attack='</title><script>alert(1)</script><img src=x onerror=alert(2)>'
        view['current_project']['name']=attack
        row=view['opportunities'][0];row.update(title=attack,summary=attack,url='javascript:alert(3)',entry_url='file:///private-key')
        row['evidence'][0].update(excerpt=attack,url='https://example.org/?q=" onmouseover="evil')
        body=share_page.render(view);parser=Elements();parser.feed(body)
        self.assertNotIn('<script>',body);self.assertIn('&lt;script&gt;',body)
        for tag,attrs in parser.rows:
            self.assertFalse(any(k.startswith('on') for k in attrs))
            if tag=='a':self.assertTrue(attrs['href'].startswith(('http://','https://')))
    def test_no_project_is_rejected_and_download_filename_is_portable(self):
        with self.assertRaises(ValueError):share_page.render({'current_project':None})
        view=copy.deepcopy(self.view);view['current_project']['name']='../name:\\with/slash\r\n"*?'
        name=share_page.filename(view,'2026-11-21T20:00:00+08:00')
        self.assertTrue(name.endswith('-2026-11-21.html'))
        self.assertFalse(any(c in name for c in '/\\:\r\n"*?'))
    def test_closed_items_are_separate_and_snapshot_does_not_mutate_source(self):
        view=copy.deepcopy(self.view);view['opportunities'][0]['ranking']['status']='closed'
        before=copy.deepcopy(view);body=share_page.render(view)
        self.assertIn('已截止 / 关闭（1）',body);self.assertIn('0 条候选',body)
        self.assertEqual(view,before)
    def test_http_download_uses_html_and_attachment_for_requested_project(self):
        server=make_server(Files(self.root/'workspace.json'),0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/api/homefeed/html?project_id='+self.session['project_id'],timeout=5) as response:
                self.assertEqual(response.headers.get_content_type(),'text/html')
                self.assertIn('attachment;',response.headers['Content-Disposition'])
                self.assertIn("filename*=UTF-8''",response.headers['Content-Disposition'])
                self.assertIn('sha256-',response.headers['Content-Security-Policy'])
                self.assertIn('合成计划',response.read().decode('utf-8'))
            with self.assertRaises(HTTPError) as error:urlopen(base+'/api/homefeed/html?project_id=missing',timeout=5)
            self.assertEqual(error.exception.code,400)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
