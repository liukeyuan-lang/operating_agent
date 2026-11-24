"""Discovery entry persistence and suppression; isolated synthetic records only."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from demo import Files,csv_cell,make_server,now,public_state,record,request_run,select_project,start_run
from leads import KINDS,add_lead,clean_target,csv_text,library,remove_lead
from test_demo import packet


class LeadTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.files=Files(Path(self.tmp.name)/'workspace.json')
    def tearDown(self):self.tmp.cleanup()
    def add(self,**overrides):
        return add_lead(self.files,{'title':'合成入口','kind':'creator','reason':'查其合作机构以发现新征集',**overrides},now())
    def test_manual_names_and_keywords_reload_as_frontier_not_qualified_opportunities(self):
        for kind in KINDS:self.add(title='合成入口'+kind,kind=kind)
        state=public_state(Files(self.files.path))
        self.assertEqual({r['kind'] for r in state['lead_library']},set(KINDS))
        self.assertEqual(len(state['frontier']),len(KINDS))
        self.assertEqual(state['results'],[])
        self.assertEqual(state['items'],[])
        self.assertTrue((self.files.path.parent/'搜索线索.csv').exists())
    def test_mixed_collections_merge_same_target_and_keep_discovery_paths(self):
        run=start_run(self.files,'合成查询');p=packet(run)
        p['followups']=[{'kind':'creator','target':'https://example.test/creator?utm_source=x',
                         'reason':'查合作机构','parent_url':p['items'][0]['url']}]
        record(self.files,p)
        def fixtures(data):
            pid=data['active_project_id']
            data['sources'].append({'id':'source','project_id':pid,'platform':'web','url':'https://example.test/creator',
                'name':'合成创作者','role':'peer','reason':'同行合作路径','seen_posts':[],
                'discovery_path':[{'label':'另一条路径','url':'https://example.test/other'}]})
            data['signals'].append({'id':'signal','project_id':pid,'platform':'xiaohongshu','key':'synthetic-topic',
                'kind':'topic','title':'合成话题','fit_reason':'可据此找到新作者','summary':'fixture','updated_at':now(),
                'evidence':[{'title':'合成内容','url':p['items'][0]['url'],'read_at':now(),'excerpt':'fixture'}],
                'heat':{'status':'unverified'}})
        self.files.change(fixtures)
        rows=library(self.files.load())
        creator=next(r for r in rows if r['kind']=='creator')
        self.assertEqual(len(creator['origins']),2)
        self.assertEqual(len(creator['discovery_path']),2)
        self.assertEqual(creator['status'],'watching')
        self.assertEqual({r['kind'] for r in rows if r['origin']!='seed'},{'creator','topic','opportunity'})
    def test_delete_survives_rediscovery_and_preserves_history_until_restored(self):
        run=start_run(self.files,'合成查询');p=packet(run);record(self.files,p)
        row=next(r for r in library(self.files.load()) if r['kind']=='organization')
        remove_lead(self.files,{'id':row['id']},now())
        p2=copy.deepcopy(p);p2['id']='second';record(self.files,p2)
        state=public_state(self.files)
        self.assertFalse(any(r['key']==row['key'] for r in state['frontier']))
        self.assertTrue(next(f for f in state['followups'] if f['id']==row['origins'][0]['id'])['discovery_disabled'])
        self.assertEqual(len(state['deleted_leads']),1)
        self.assertEqual(sum(f.get('origin')!='seed' for f in self.files.load()['followups']),1)
        self.assertEqual(len(self.files.load()['items']),1)
        remove_lead(self.files,{'id':row['id']},now(),restore=True)
        self.assertTrue(any(r['key']==row['key'] for r in public_state(self.files)['frontier']))
        self.assertEqual(public_state(self.files)['deleted_leads'],[])
    def test_deleted_entry_not_silently_readded_and_projects_are_isolated(self):
        first=self.add();original=self.files.load()['active_project_id']
        remove_lead(self.files,{'id':first['id']},now())
        with self.assertRaises(ValueError):self.add()
        request_run(self.files,{'mode':'new','name':'合成第二项目','direction':'测试','assets_brief':'无素材'})
        self.assertEqual(library(self.files.load(),deleted=True),[])
        second=self.add()
        self.assertNotEqual(second['project_id'],original)
        with self.assertRaises(ValueError):remove_lead(self.files,{'id':first['id']},now(),restore=True)
        select_project(self.files,original)
        self.assertEqual(library(self.files.load()),[])
        self.assertEqual(len(library(self.files.load(),deleted=True)),1)
    def test_target_dedup_platform_conflicts_and_csv_formula_safety(self):
        self.add(target='https://example.test/community/?utm_source=one')
        with self.assertRaises(ValueError):self.add(target='https://example.test/community')
        for bad in ('javascript:alert(1)','file:///secret','https://user:password@example.test/'):
            with self.assertRaises(ValueError):clean_target(bad)
        with self.assertRaises(ValueError):self.add(target='https://www.douyin.com/user/test',platform='xiaohongshu')
        self.add(title='=danger()',kind='topic')
        self.assertIn("'=danger()",csv_text(self.files.load(),csv_cell))
    def test_api_add_delete_restore_export_and_csrf(self):
        server=make_server(self.files,0);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/state') as response:state=json.load(response)
            payload={'title':'合成手工入口','kind':'website','target':'https://example.test/community','reason':'找近期征集'}
            def send(route,obj,token=True):
                headers={'Content-Type':'application/json'}
                if token:headers['X-Demo-Token']=state['csrf']
                with urlopen(Request(base+route,data=json.dumps(obj).encode(),headers=headers)) as response:return json.load(response)
            with self.assertRaises(HTTPError):send('/api/leads',payload,False)
            added=send('/api/leads',payload)
            send('/api/leads/delete',{'id':added['id']})
            with urlopen(base+'/api/state') as response:deleted=json.load(response)
            self.assertEqual(deleted['lead_library'],[])
            self.assertEqual(deleted['frontier'],[])
            self.assertEqual(len(deleted['deleted_leads']),1)
            send('/api/leads/restore',{'id':added['id']})
            with urlopen(base+'/api/leads.csv') as response:
                self.assertIn('合成手工入口',response.read().decode('utf-8-sig'))
            with self.assertRaises(HTTPError):send('/api/leads',{**payload,'target':'javascript:alert(1)'})
        finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
