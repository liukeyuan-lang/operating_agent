"""Synthetic fixtures in temporary directories; no browser or external account actions."""
import copy
import json
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import homefeed as h
from demo import Files,make_server


def note():
    stamp=h.now();quote='合成计划正在招募，参与可获现金激励，并由官方展示作品。'
    proof={'source_id':'official','quote':quote}
    return {'url':'https://www.xiaohongshu.com/explore/'+'a'*24+'?xsec_token=fixture',
            'title':'合成首页计划','read_at':stamp,'decision':'keep','reason':'仅用于测试的合成机会',
            'opportunity':{'title':'合成计划','summary':'不是真实机会','evidence':[{'id':'official','url':'https://example.org/official',
                'excerpt':quote,'read_at':stamp,'official':True,'authority_basis':'测试身份依据'}],
                'open_status':{'value':'open','evidence':proof},'deadline':{'label':'未明确截止时间'},
                'benefits':{'traffic':{'score':None,'reason':'未知'},'cash':{'score':4,'reason':'合成奖励','evidence':proof},
                    'commercial':{'score':None,'reason':'未知'},'exposure':{'score':3,'reason':'合成展示','evidence':proof}},
                'uncertainties':['权利条款待核实']},
            'interactions':{'like':{'status':'performed','before':False,'after':True,'evidence':'合成：已点赞状态'},
                            'collect':{'status':'already_done','before':True,'after':True,'evidence':'合成：原先已收藏'}}}


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.files=h.FeedFiles(self.path/'homepage.json')
        self.session=h.create_session(self.files,{'login_confirmed':True,'allow_interactions':True})
        h.task(self.files,self.session['id'],True)
    def tearDown(self):self.tmp.cleanup()
    def packet(self,note_value=None,identifier='batch-1'):
        return {'session_id':self.session['id'],'packet_id':identifier,'refreshes':1,'cards':20,'notes':[note_value or note()]}
    def test_preconditions_and_single_active_task_resume(self):
        with self.assertRaises(ValueError):h.create_session(self.files,{})
        again=h.create_session(self.files,{'login_confirmed':True,'allow_interactions':True})
        self.assertEqual(again['id'],self.session['id']);self.assertTrue(again['resumed'])
        self.assertEqual(len(self.files.load()['sessions']),1)
    def test_atomic_idempotence_and_note_dedup(self):
        packet=self.packet();h.record(self.files,packet)
        self.assertTrue(h.record(self.files,packet)['duplicate'])
        changed=copy.deepcopy(packet);changed['cards']=21
        with self.assertRaises(ValueError):h.record(self.files,changed)
        changed=copy.deepcopy(packet);changed['packet_id']='actions-receipt';changed['refreshes']=0;changed['cards']=0
        changed['notes'][0]['interactions']['like']={'status':'already_done','before':True,'after':True,'evidence':'合成：已点赞'}
        h.record(self.files,changed)
        data=self.files.load();self.assertEqual(len(data['opportunities']),1);self.assertNotIn('authors',data)
        self.assertEqual(data['sessions'][0]['counts'],{'refreshes':1,'cards':20,'details':1,'kept':1,'likes':1,'collects':0})
        self.assertIn('合成计划',(self.path/'首页探索记录.md').read_text(encoding='utf-8'))
    def test_rejects_follow_unverified_reward_and_false_success(self):
        for mutate in [lambda p:p.update(follow=True),
                       lambda p:p['notes'][0]['interactions'].update(follow={'status':'performed'}),
                       lambda p:p['notes'][0]['opportunity']['benefits']['cash'].update(evidence={'source_id':'official','quote':'不存在的证据'}),
                       lambda p:p['notes'][0]['interactions']['like'].update(after=False)]:
            packet=self.packet();mutate(packet);before=self.files.path.read_bytes()
            with self.assertRaises(ValueError):h.record(self.files,packet)
            self.assertEqual(before,self.files.path.read_bytes())
    def test_unknown_or_expired_not_liked_and_stale_scores_downgraded(self):
        n=note();n['opportunity']['open_status']={'value':'unknown'}
        with self.assertRaises(ValueError):h.record(self.files,self.packet(n))
        n.pop('interactions');h.record(self.files,self.packet(n))
        row=self.files.load()['opportunities'][0];self.assertEqual(h.rank(row,h.project_for(self.files.load()),h.now())['status'],'unknown')
        later=(h.instant(h.now())+timedelta(days=8)).isoformat()
        self.assertEqual(h.rank(row,h.project_for(self.files.load()),later)['total'],0)
        self.assertEqual(h.rank(row,h.project_for(self.files.load()),later)['known_weight'],0)
    def test_preference_score_replaces_materials_and_invalidates_when_preferences_change(self):
        h.create_session(self.files,{'mode':'continue','login_confirmed':True,'preferences':'偏好实验影像'})
        n=note();n['opportunity']['preference_match']={'score':5,'reason':'符合用户填写的实验影像偏好'}
        h.record(self.files,self.packet(n));data=self.files.load();row=data['opportunities'][0]
        self.assertEqual(h.rank(row,h.project_for(data),h.now())['total'],39)
        h.create_session(self.files,{'mode':'continue','login_confirmed':True,'preferences':'偏好品牌商业共创'})
        ranked=h.rank(row,h.project_for(self.files.load()),h.now())
        self.assertEqual(ranked['total'],29);self.assertIsNone(ranked['components'][-1]['score'])

    def test_stop_and_resume_after_finish(self):
        self.assertEqual(h.stop_session(self.files,self.session['id'])['status'],'stopping')
        self.assertEqual(h.task(self.files,self.session['id'])['next_action'],'stop')
        h.finish(self.files,self.session['id'],'completed','用户停止，已保存真实记录')
        self.assertEqual(h.task(self.files,self.session['id'],True)['next_action'],'report')
        with self.assertRaises(ValueError):h.record(self.files,self.packet())
        new=h.create_session(self.files,{'login_confirmed':True,'allow_interactions':True})
        self.assertNotEqual(new['id'],self.session['id'])
    def test_skip_remembered_but_not_a_candidate(self):
        n=note();n={k:n[k] for k in ('url','title','read_at','reason')};n['decision']='skip'
        h.record(self.files,self.packet(n));data=self.files.load()
        self.assertFalse(data['opportunities']);self.assertNotIn('authors',data);self.assertEqual(len(data['observations']),1)
        self.assertEqual(h.task(self.files,self.session['id'])['seen_notes'][0]['decision'],'skip')
    def test_same_title_without_confirmed_organizer_does_not_merge_different_notes(self):
        first=note()
        h.record(self.files,self.packet(first))
        second=copy.deepcopy(first);second['url']='https://www.xiaohongshu.com/explore/'+'c'*24
        h.record(self.files,self.packet(second,'other-event'))
        self.assertEqual(len(self.files.load()['opportunities']),2)
    def test_project_weights_recompute_existing_ratings_and_export(self):
        h.create_session(self.files,{'mode':'continue','login_confirmed':True,'preferences':'偏好实验影像'})
        n=note();n['opportunity']['preference_match']={'score':5,'reason':'符合实验影像偏好'}
        h.record(self.files,self.packet(n))
        weights={'traffic':25,'cash':40,'commercial':15,'exposure':10,'preferences':10}
        h.create_session(self.files,{'mode':'continue','login_confirmed':True,'weights':weights})
        data=self.files.load();ranked=h.rank(data['opportunities'][0],h.project_for(data),h.now())
        self.assertEqual(ranked['total'],48)
        exported=(self.path/'首页候选机会.csv').read_text(encoding='utf-8-sig')
        self.assertIn('用户偏好',exported);self.assertIn('48.0',exported);self.assertNotIn('素材匹配',exported)

    def test_http_page_session_csrf_and_exports(self):
        server=make_server(Files(self.path/'workspace.json'),0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/api/homefeed') as r:state=json.load(r)
            with urlopen(base+'/explore') as r:html=r.read().decode()
            self.assertIn('/homefeed.js',html);self.assertEqual(html.count('data-tab='),2)
            with self.assertRaises(HTTPError):urlopen(Request(base+'/api/homefeed/stop',data=b'{}',headers={'Content-Type':'application/json'}))
            with urlopen(Request(base+'/api/homefeed/stop',data=json.dumps({'id':self.session['id']}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':state['csrf']})) as r:
                self.assertEqual(json.load(r)['status'],'stopping')
            with urlopen(base+'/api/homefeed/report') as r:self.assertIn('首页探索记录',r.read().decode())
        finally:server.shutdown();server.server_close();thread.join()

    def test_old_records_migrate_without_losing_candidates_and_remove_author_feature(self):
        h.record(self.files,self.packet())
        old=self.files.load();old['version']=1;old.pop('projects');old.pop('active_project_id')
        for key in ('sessions','observations','opportunities'):
            for row in old[key]:row.pop('project_id',None)
        old['authors']=[{'name':'旧官方作者'}];old['opportunities'][0]['author']={'name':'旧官方作者'}
        self.files.path.write_text(json.dumps(old,ensure_ascii=False),encoding='utf-8')
        (self.path/'官方作者.json').write_text('[]',encoding='utf-8')
        data=self.files.load()
        self.assertEqual(len(data['projects']),1);self.assertEqual(data['projects'][0]['name'],'首页探索')
        self.assertEqual(data['opportunities'][0]['id'],old['opportunities'][0]['id'])
        self.assertNotIn('authors',data);self.assertNotIn('author',data['opportunities'][0])
        self.files.change(lambda current:None)
        self.assertFalse((self.path/'官方作者.json').exists())
        self.assertNotIn('官方作者',(self.path/'首页候选机会.csv').read_text(encoding='utf-8-sig'))

    def test_projects_isolate_history_and_preferences_and_continue_without_materials(self):
        h.record(self.files,self.packet())
        h.finish(self.files,self.session['id'],'completed','合成结束')
        first_pid=self.session['project_id']
        second=h.create_session(self.files,{'mode':'new','name':'项目乙','preferences':'偏好共创','login_confirmed':True})
        self.assertNotEqual(first_pid,second['project_id']);self.assertFalse(second['project']['material_pack_ids'])
        h.task(self.files,second['id'],True)
        view=h.notebook(self.files.load(),[],second['project_id'])
        self.assertFalse(view['opportunities']);self.assertFalse(view['observations'])
        h.finish(self.files,second['id'],'completed','合成结束')
        again=h.create_session(self.files,{'mode':'continue','project_id':first_pid,'preferences':'现金优先','login_confirmed':True})
        context=h.task(self.files,again['id'],True)
        self.assertEqual(context['project']['preferences'],'现金优先');self.assertEqual(len(context['seen_notes']),1)
        self.assertEqual(len(context['opportunity_ids']),1);self.assertNotIn('official_authors',context)
        self.assertEqual(len(self.files.load()['projects']),2)

    def test_exploration_context_and_scoring_never_read_materials(self):
        from unittest.mock import patch
        packs=[{'id':'pack','analysis_id':'v1','deleted':False}]
        h.attach_pack(self.files,self.session['project_id'],'pack',packs)
        (self.path/'workspace.json').write_text('not needed by exploration',encoding='utf-8')
        with patch('material_library.view_packs',side_effect=AssertionError('不应读取素材理解')):
            context=h.task(self.files,self.session['id'],True)
            self.assertNotIn('material_packs',context);self.assertNotIn('material_pack_ids',context['project'])
            h.record(self.files,self.packet())
        self.assertEqual(h.notebook(self.files.load(),packs)['opportunities'][0]['ranking']['total'],29)
        n=note();n['opportunity']['asset_matches']=[]
        with self.assertRaisesRegex(ValueError,'不读取或评估素材'):h.record(self.files,self.packet(n,'no-assets'))

    def test_only_one_project_can_drive_browser_at_a_time(self):
        other=h.create_session(self.files,{'mode':'new','name':'另一个项目','login_confirmed':True})
        with self.assertRaisesRegex(ValueError,'仍在使用浏览器'):h.task(self.files,other['id'],True)
        self.assertEqual(h.task(self.files,other['id'])['session']['status'],'queued')
        h.finish(self.files,self.session['id'],'completed','结束前项')
        self.assertEqual(h.task(self.files,other['id'],True)['next_action'],'browse')

    def test_invalid_project_or_materials_does_not_mutate_existing_records(self):
        for payload in [{'mode':'continue','project_id':'missing'},
                        {'mode':'new','material_pack_ids':['missing']},
                        {'mode':'new','preferences':None}]:
            before=self.files.path.read_bytes()
            with self.assertRaises(ValueError):h.create_session(self.files,{**payload,'login_confirmed':True})
            self.assertEqual(before,self.files.path.read_bytes())

    def test_custom_weights_validate_total_and_continue_preserves_them(self):
        weights={'traffic':20,'cash':35,'commercial':20,'exposure':15,'preferences':10}
        continued=h.create_session(self.files,{'mode':'continue','login_confirmed':True,'weights':weights})
        self.assertEqual(continued['project']['weights'],weights)
        self.assertEqual(h.create_session(self.files,{'mode':'continue','login_confirmed':True})['project']['weights'],weights)
        for invalid in [{**weights,'cash':36},{**weights,'cash':-1},{**weights,'cash':True},
                        {**weights,'cash':35.0},{'traffic':100}]:
            before=self.files.path.read_bytes()
            with self.assertRaises(ValueError):h.create_session(self.files,{'mode':'continue','login_confirmed':True,'weights':invalid})
            self.assertEqual(before,self.files.path.read_bytes())

    def test_blank_preferences_cannot_receive_assumed_bonus(self):
        n=note();n['opportunity']['preference_match']={'score':5,'reason':'不能假定用户的偏好'}
        with self.assertRaisesRegex(ValueError,'未填写偏好'):h.record(self.files,self.packet(n))
        n['opportunity']['preference_match']={'score':None,'reason':'未填写偏好'}
        h.record(self.files,self.packet(n))
        self.assertIsNone(h.notebook(self.files.load(),[])['opportunities'][0]['ranking']['components'][-1]['score'])

    def test_http_project_material_directory_cache_and_independent_removal(self):
        from test_material_understanding import FakeGemini
        client=FakeGemini();directory=self.path/'项目素材';directory.mkdir()
        (directory/'说明.txt').write_text('合成项目素材，不是真实作品',encoding='utf-8')
        server=make_server(Files(self.path/'workspace.json'),0,lambda:client)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def get(path):
            with urlopen(base+path,timeout=5) as response:return json.load(response)
        csrf=get('/api/homefeed')['csrf']
        def post(path,payload):
            with urlopen(Request(base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Demo-Token':csrf}),timeout=5) as response:return json.load(response)
        try:
            job=post('/api/materials/analyze',{'directory':str(directory)})
            deadline=time.monotonic()+8
            while job['status'] in {'queued','running'} and time.monotonic()<deadline:
                time.sleep(.02);job=get('/api/materials/status?id='+job['id'])
            self.assertEqual(job['status'],'complete')
            binding={'material_directory':str(directory),'material_analysis_id':job['id']}
            first=post('/api/homefeed/start',{'mode':'new','name':'有素材项目','preferences':'实验影像','login_confirmed':True,**binding})
            view=get('/api/homefeed?project_id='+first['project_id'])
            self.assertEqual(len(view['material_packs']),1)
            self.assertEqual(view['material_packs'][0]['name'],'合成素材项目')
            self.assertEqual(view['current_project']['preferences'],'实验影像')
            self.assertNotIn('authors',view);self.assertNotIn('official_authors',view['stats'])
            calls=client.calls
            second=post('/api/homefeed/start',{'mode':'new','name':'无素材项目','login_confirmed':True})
            self.assertFalse(get('/api/homefeed?project_id='+second['project_id'])['material_packs'])
            cached=post('/api/materials/analyze',{'directory':str(directory)})
            self.assertEqual(cached['id'],job['id']);self.assertEqual(client.calls,calls)
            pack=post('/api/homefeed/library/add',{'project_id':second['project_id'],**binding})
            self.assertEqual(len(get('/api/homefeed?project_id='+second['project_id'])['material_packs']),1)
            post('/api/homefeed/library/delete',{'project_id':second['project_id'],'id':pack['id']})
            self.assertFalse(get('/api/homefeed?project_id='+second['project_id'])['material_packs'])
            self.assertEqual(len(get('/api/homefeed?project_id='+first['project_id'])['material_packs']),1)
            continued=post('/api/homefeed/start',{'mode':'continue','project_id':first['project_id'],'login_confirmed':True})
            self.assertEqual(continued['id'],first['id']);self.assertEqual(client.calls,calls)
            self.assertTrue((directory/'说明.txt').is_file())
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
