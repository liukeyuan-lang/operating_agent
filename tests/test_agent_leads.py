"""AI manages candidates; code never selects the next search or fabricates a read."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from demo import Files,now,public_state,request_run,start_run
from leads import add_lead,library,remove_lead,seed_initial,update_lead

ROOT=Path(__file__).resolve().parents[1]


class AgentLeadTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.files=Files(Path(self.tmp.name)/'workspace.json')
    def tearDown(self):self.tmp.cleanup()
    def add(self):
        return add_lead(self.files,{'title':'合成创作社区','kind':'website','target':'https://example.test/community',
            'reason':'用于隔离测试，寻找新的活动来源'},now(),actor='agent')
    def test_seed_is_candidate_not_read_or_activity_and_start_does_not_search(self):
        run=start_run(self.files)
        state=public_state(self.files)
        seeds=[r for r in state['lead_library'] if r['origin']=='seed']
        self.assertTrue(any(r['target']=='https://jimeng.jianying.com/ai-tool/explore' for r in seeds))
        self.assertEqual(state['selection_policy'],'agent_decides')
        self.assertEqual(state['items'],[])
        self.assertEqual(state['sources'],[])
        self.assertTrue(all(v==0 for v in run['counts'].values()))
        self.assertTrue(all(r['status']=='new' and not r.get('read_at') for r in seeds))
    def test_new_projects_receive_independent_defaults_and_continuing_preserves_decisions(self):
        payload={'mode':'new','name':'合成甲','direction':'测试','assets_brief':'暂无素材'}
        first=request_run(self.files,payload)
        row=next(r for r in library(self.files.load()) if r['origin']=='seed')
        update_lead(self.files,{'id':row['id'],'status':'blocked','decision':'实际访问受阻；隔离测试，不是真实页面结论'},now())
        request_run(self.files,{'mode':'continue','project_id':first['project_id']})
        self.assertEqual(library(self.files.load())[0]['status'],'blocked')
        self.assertEqual(self.files.change(lambda d:seed_initial(d,now()))['added'],[])
        second=request_run(self.files,{**payload,'name':'合成乙'})
        self.assertNotEqual(first['project_id'],second['project_id'])
        self.assertEqual(library(self.files.load())[0]['status'],'new')
        self.assertNotEqual(library(self.files.load())[0]['id'],row['id'])
    def test_default_cannot_resurrect_user_deletion_and_ai_cannot_override_it(self):
        self.files.change(lambda data:seed_initial(data,now()))
        row=library(self.files.load())[0]
        remove_lead(self.files,{'id':row['id']},now())
        self.assertEqual(self.files.change(lambda d:seed_initial(d,now()))['added'],[])
        self.assertFalse(any(r['key']==row['key'] for r in library(self.files.load())))
        with self.assertRaisesRegex(ValueError,'用户'):
            remove_lead(self.files,{'id':row['id'],'decision':'尝试重新判断'},now(),restore=True,actor='agent')
        remove_lead(self.files,{'id':row['id']},now(),restore=True)
        self.assertTrue(any(r['key']==row['key'] for r in library(self.files.load())))
    def test_agent_decision_on_source_preserves_raw_evidence_and_overrides_watch_status(self):
        run=start_run(self.files);pid=run['project_id']
        source={'id':'fixture-source','project_id':pid,'platform':'web','url':'https://example.test/creator',
            'name':'合成创作者','role':'peer','reason':'从作品发现其合作机构','seen_posts':['https://example.test/post'],
            'last_checked_at':None,'latest_observation':'合成观察'}
        self.files.change(lambda d:d['sources'].append(copy.deepcopy(source)))
        row=next(r for r in library(self.files.load()) if r['kind']=='creator')
        result=update_lead(self.files,{'id':row['id'],'status':'blocked','next_step':'换一个公开入口',
            'decision':'隔离测试：该入口受阻，暂时探索其他来源','run_id':run['id']},now())
        self.assertEqual(self.files.load()['sources'][0],source)
        self.assertEqual(result['status'],'blocked')
        self.assertFalse(any(r['key']==row['key'] for r in public_state(self.files)['frontier']))
        last=self.files.load()['events'][-1]
        self.assertEqual((last['actor'],last['run_id']),('agent',run['id']))
        self.assertIn('受阻',last['message'])
        self.assertEqual(public_state(self.files)['results'],[])
    def test_agent_pruning_is_reversible_and_requires_reason(self):
        row=self.add()
        with self.assertRaises(ValueError):remove_lead(self.files,{'id':row['id']},now(),actor='agent')
        remove_lead(self.files,{'id':row['id'],'decision':'与当前项目关系弱，剪去此分支'},now(),actor='agent')
        self.assertEqual(library(self.files.load()),[])
        self.assertEqual(self.files.load()['lead_deletions'][0]['actor'],'agent')
        remove_lead(self.files,{'id':row['id'],'decision':'发现新的相关材料，重新探索'},now(),restore=True,actor='agent')
        self.assertEqual(len(library(self.files.load())),1)
    def test_bad_edits_and_cross_project_or_fake_run_are_rejected_atomically(self):
        row=self.add();revision=self.files.load()['revision']
        for changes in ({'status':'qualified'},{'target':'https://example.test/other'},
                        {'facts':{'ai_policy':'allowed'}},{'run_id':'missing'}):
            with self.assertRaises(ValueError):update_lead(self.files,{'id':row['id'],'decision':'测试理由',**changes},now())
        self.assertEqual(self.files.load()['revision'],revision)
        request_run(self.files,{'mode':'new','name':'第二合成项目','direction':'测试','assets_brief':'无素材'})
        with self.assertRaises(ValueError):update_lead(self.files,{'id':row['id'],'decision':'跨项目不可修改'},now())
    def test_real_cli_round_trip_and_list_does_not_dispatch_or_mutate(self):
        argument=Path(self.tmp.name)/'args.json'
        def cli(action,payload=None):
            command=[sys.executable,'-X','utf8',str(ROOT/'demo.py'),'--data',str(self.files.path),'lead',action]
            if payload is not None:
                argument.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                command+=['--file',str(argument)]
            result=subprocess.run(command,cwd=self.tmp.name,capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        cli('seed');before=self.files.path.read_bytes()
        listed=cli('list')
        self.assertEqual(listed['selection_policy'],'agent_decides')
        self.assertNotIn('next_lead',listed)
        self.assertEqual(self.files.path.read_bytes(),before)
        row=cli('add',{'title':'合成CLI话题','kind':'topic','reason':'合成素材相关的新方向'})
        self.assertEqual(row['origin'],'agent')
        row=cli('update',{'id':row['id'],'decision':'测试自主选择下一步','next_step':'搜索这个对象的合作方','status':'watching'})
        self.assertIn('合作方',row['next_step'])
        cli('delete',{'id':row['id'],'decision':'测试剪枝'})
        self.assertTrue(any(r['id']==row['id'] for r in cli('list')['deleted_leads']))
        cli('restore',{'id':row['id'],'decision':'测试恢复自己的剪枝'})
        self.assertTrue(any(r['id']==row['id'] for r in cli('list')['lead_library']))
