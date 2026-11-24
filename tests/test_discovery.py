"""Opportunity-first workflow, evidence scoring and independent library; synthetic only."""
import copy
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from demo import Files,finish,make_server,now,public_state,record,request_run,start_run
from discovery import DEFAULT_REQUIREMENTS,DEFAULT_SEEDS,rank_candidate,save_assessment
from leads import library,remove_lead,seed_initial
from material_library import add_pack,delete_pack
from material_understanding import MaterialService
from test_material_understanding import FakeGemini
from workflow import migrate,project


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.files=Files(self.root/'data/workspace.json')
    def tearDown(self):self.tmp.cleanup()
    def candidate(self):
        run=start_run(self.files)
        record(self.files,{'id':'synthetic','run_id':run['id'],'items':[{
            'title':'合成共创计划','url':'https://example.test/call','fit':'strong','fit_reason':'隔离测试，无真实机会',
            'official_sources':[{'id':'official','url':'https://example.test/rules','read_at':now(),
                'authority_basis':'测试夹具','excerpt':'合成规则：非排他性的共创计划；正在开放；流量扶持和现金激励；商业合作与展示。'}]}]})
        obj=self.files.load()['items'][0]
        return run,obj
    def assessment(self,obj,score=3):
        evidence={'source_id':'official','quote':'合成规则：非排他性的共创计划；正在开放；流量扶持和现金激励；商业合作与展示。'}
        return {'id':obj['id'],'requirements':[{'requirement':text,'status':'pass','reason':'合成官方规则说明','evidence':evidence}
                for text in ['非排他性的共创计划','正在开放的']],
            'benefits':{k:{'score':score,'reason':'合成评分尺度','evidence':evidence} for k in ['traffic','cash','commercial','exposure']},'asset_matches':[]}
    def ranking(self):return public_state(self.files)['items'][0]['ranking']
    def test_new_defaults_no_material_model_and_seeds_can_be_configured(self):
        req=request_run(self.files,{'mode':'new'})
        p=req['profile_snapshot'];self.assertEqual(p['name'],'新探索');self.assertEqual(p['exploration_requirements'],DEFAULT_REQUIREMENTS)
        self.assertEqual(p['seed_keywords'],DEFAULT_SEEDS);self.assertNotIn('materials',p);self.assertEqual(p['asset_references'],[])
        self.assertTrue(set(DEFAULT_SEEDS)<={r['target'] for r in library(self.files.load())})
        other=request_run(self.files,{'mode':'new','seed_keywords':'自定义\n 自定义 \n新线索'})
        self.assertEqual(other['profile_snapshot']['seed_keywords'],['自定义','新线索'])
        request_run(self.files,{'mode':'continue','project_id':other['project_id']})
        self.assertEqual(project(self.files.load())['seed_keywords'],['自定义','新线索'])
        self.assertFalse((self.root/'data/materials.json').exists())
    def test_custom_seed_deletion_is_not_resurrected(self):
        request_run(self.files,{'mode':'new','seed_keywords':['独特入口']})
        row=next(r for r in library(self.files.load()) if r['target']=='独特入口')
        remove_lead(self.files,{'id':row['id']},now());self.files.change(lambda d:seed_initial(d,now()))
        self.assertFalse(any(r['target']=='独特入口' for r in library(self.files.load())))
    def test_active_legacy_round_migrates_without_changing_completed_history(self):
        run=start_run(self.files)
        data=self.files.load();data['runs'][0].update(scenario='weekly_planning',targets={'focus_areas':3,'searches':6})
        ended=copy.deepcopy(data['runs'][0]);ended.update(id='historical',status='completed');data['runs'].append(ended)
        upgraded=migrate(data)
        self.assertEqual(upgraded['runs'][0]['scenario'],'opportunity_discovery')
        self.assertNotIn('focus_areas',upgraded['runs'][0]['targets'])
        self.assertEqual(upgraded['runs'][1]['scenario'],'weekly_planning')
    def test_migration_preserves_binding_history_and_publishing_then_is_idempotent(self):
        old=self.files.load();p=project(old);p.pop('discovery_version',None)
        p['materials']={'directory':'test-only','fingerprint':'fixture-fingerprint','analysis_id':'analysis1'}
        p['asset_references']=[{'id':'legacy','title':'测试素材'}]
        pub=copy.deepcopy(p);pub.update(id='pub',workspace='publishing');old['projects'].append(pub)
        first=migrate(copy.deepcopy(old));second=migrate(copy.deepcopy(old))
        self.assertEqual(first['material_packs'],second['material_packs'])
        self.assertNotIn('materials',project(first));self.assertEqual(project(first)['asset_references'],[])
        self.assertEqual(project(first)['legacy_material_binding'],p['materials']);self.assertEqual(first['projects'][1]['materials'],pub['materials'])
        first['material_packs'][0]['deleted']=True
        self.assertEqual(len(migrate(first)['material_packs']),1);self.assertTrue(first['material_packs'][0]['deleted'])
    def test_scores_use_public_weights_and_materials_are_not_a_gate(self):
        _,obj=self.candidate();save_assessment(self.files,self.assessment(obj,5),now())
        r=self.ranking();self.assertEqual(r['total'],90);self.assertEqual(r['known_weight'],90);self.assertEqual(r['status'],'matched')
        self.assertEqual([c['points'] for c in r['components']],[30,25,20,15,0])
        self.assertEqual(public_state(self.files)['results'],[])  # old strict submission gate has no influence.
        self.assertEqual(len(public_state(self.files)['candidate_opportunities']),1)
        self.files.change(lambda d:d['items'][0].update(participation={'asset_fit':{'status':'fail','reason':'历史素材不符'}}))
        self.assertEqual(self.ranking()['status'],'matched')
    def test_value_order_prioritizes_traffic_and_cash_and_keeps_unassessed_last(self):
        run,obj=self.candidate();payload=self.assessment(obj)
        payload['benefits']['traffic']['score']=5;payload['benefits']['cash']['score']=5
        payload['benefits']['commercial']['score']=0;payload['benefits']['exposure']['score']=0
        save_assessment(self.files,payload,now())
        other=copy.deepcopy(obj);other.update(title='合成曝光合作',url='https://example.test/other')
        third=copy.deepcopy(obj);third.update(title='合成尚待评估',url='https://example.test/pending')
        record(self.files,{'id':'more','run_id':run['id'],'items':[other,third]})
        other=next(i for i in self.files.load()['items'] if i['url']=='https://example.test/other')
        payload=self.assessment(other);payload['benefits']['traffic']['score']=0;payload['benefits']['cash']['score']=0
        payload['benefits']['commercial']['score']=5;payload['benefits']['exposure']['score']=5
        save_assessment(self.files,payload,now())
        rows=public_state(self.files)['candidate_opportunities']
        self.assertEqual([i['ranking']['total'] for i in rows],[55,35,None])
    def test_unknowns_have_no_invented_value_and_unassessed_is_distinct(self):
        _,obj=self.candidate();self.assertIsNone(self.ranking()['total'])
        payload=self.assessment(obj)
        payload['requirements'][0]={'requirement':'非排他性的共创计划','status':'unknown','reason':'授权条款不明'}
        payload['benefits']={k:{'score':None,'reason':'尚未找到证据'} for k in payload['benefits']}
        save_assessment(self.files,payload,now());r=self.ranking()
        self.assertEqual((r['total'],r['known_weight'],r['status']),(0,0,'pending'))
        self.assertTrue(all(c['score'] is None for c in r['components']))
    def test_official_conflict_and_expiration_exclude_candidates(self):
        _,obj=self.candidate();payload=self.assessment(obj);payload['requirements'][0]['status']='fail'
        save_assessment(self.files,payload,now());self.assertEqual(self.ranking()['status'],'excluded')
        self.assertEqual(public_state(self.files)['candidate_opportunities'],[])
        save_assessment(self.files,self.assessment(obj),now())
        self.files.change(lambda d:d['items'][0].update(facts={'deadline':{'at':'2020-01-01T00:00:00+08:00'}}))
        self.assertEqual(self.ranking()['status'],'excluded')
    def test_scores_and_confirmed_conditions_need_actual_fresh_quotes(self):
        _,obj=self.candidate();payload=self.assessment(obj)
        payload['benefits']['cash']['evidence']={'source_id':'official','quote':'不存在的现金承诺'}
        with self.assertRaisesRegex(ValueError,'官方'):save_assessment(self.files,payload,now())
        self.files.change(lambda d:d['items'][0]['official_sources'][0].update(read_at='2020-01-01T00:00:00+08:00'))
        with self.assertRaisesRegex(ValueError,'官方'):save_assessment(self.files,self.assessment(obj),now())
    def test_changed_goals_or_stale_evidence_invalidate_scores(self):
        _,obj=self.candidate();save_assessment(self.files,self.assessment(obj),now())
        later=(datetime.now(timezone.utc)+timedelta(days=8)).isoformat()
        stale=rank_candidate(self.files.load()['items'][0],project(self.files.load()),[],later)
        self.assertEqual(stale['known_weight'],0);self.assertEqual(stale['status'],'pending')
        request_run(self.files,{'mode':'continue','exploration_requirements':'新的目标'})
        self.assertIsNone(self.ranking()['total']);self.assertEqual(self.ranking()['status'],'pending')
    def test_global_material_bonus_can_be_deleted_without_losing_opportunity(self):
        _,obj=self.candidate();payload=self.assessment(obj)
        self.files.change(lambda d:d['material_packs'].append({'id':'pack','name':'合成素材','analysis_id':'v1','assets':[],'deleted':False}))
        payload['asset_matches']=[{'pack_id':'pack','analysis_id':'v1','score':5,'reason':'内容与媒介匹配'}]
        save_assessment(self.files,payload,now());self.assertEqual(self.ranking()['total'],64)
        delete_pack(self.files,'pack',now());self.assertEqual(self.ranking()['total'],54)
        self.assertEqual(self.ranking()['status'],'matched');self.assertEqual(len(self.files.load()['items']),1)
        with self.assertRaises(ValueError):save_assessment(self.files,payload,now())
    def test_completion_requires_assessment_but_never_a_weekly_plan(self):
        run,obj=self.candidate()
        with self.assertRaisesRegex(ValueError,'评估'):finish(self.files,run['id'],'未评分')
        save_assessment(self.files,self.assessment(obj),now())
        finish(self.files,run['id'],'合成评分完成');self.assertEqual(self.files.load()['weekly_plans'],[])
    def test_library_http_cache_media_delete_and_csv_are_independent_of_projects(self):
        directory=self.root/'materials';directory.mkdir();source=directory/'说明.txt';source.write_text('仅测试素材',encoding='utf-8')
        client=FakeGemini();server=make_server(self.files,0,lambda:client)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        def get(path):
            with urlopen(base+path,timeout=5) as r:return json.load(r)
        csrf=get('/api/state')['csrf']
        def post(path,payload):
            with urlopen(Request(base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Demo-Token':csrf}),timeout=5) as r:return json.load(r)
        service=MaterialService(self.root/'data/materials.json',lambda:client)
        try:
            req=post('/api/exploration/requests',{'mode':'new'});self.assertEqual(client.calls,0)
            job=service.start(str(directory));service.futures[job['id']].result(timeout=8)
            binding={'material_directory':str(directory),'material_analysis_id':job['id']}
            pack=post('/api/library/add',binding);self.assertEqual(client.calls,1)
            self.assertEqual(post('/api/library/add',binding)['id'],pack['id']);self.assertEqual(client.calls,1)
            other=post('/api/exploration/requests',{'mode':'new'})
            self.assertEqual(len(get('/api/state?project_id='+other['project_id'])['material_packs']),1)
            self.assertNotIn('materials',get('/api/state')['current_project'])
            path='/api/media/'+get('/api/state')['material_packs'][0]['assets'][0]['id']+'?library_pack='+pack['id']
            with urlopen(base+path) as r:self.assertEqual(r.read(),source.read_bytes())
            run,obj=self.candidate();post('/api/assessments',self.assessment(obj))
            with urlopen(base+'/api/candidates.csv') as r:self.assertIn('合成共创计划',r.read().decode('utf-8-sig'))
            with urlopen(base+'/discovery.js') as r:self.assertEqual(r.status,200)
            post('/api/library/delete',{'id':pack['id']});self.assertTrue(source.exists());self.assertEqual(client.calls,1)
            self.assertEqual(get('/api/state')['material_packs'],[])
            with self.assertRaises(HTTPError):urlopen(base+path)
            self.assertTrue((self.root/'data/素材库.csv').exists());self.assertTrue((self.root/'data/候选机会评分.csv').exists())
        finally:service.pool.shutdown(wait=True);server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
