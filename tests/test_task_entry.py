"""A new session resolves the requested task, not whichever project the UI selected."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from demo import Files,finish,request_run,select_project,task_context

ROOT=Path(__file__).resolve().parents[1]


class TaskEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.files=Files(Path(self.tmp.name)/'workspace.json')
        self.first=request_run(self.files,{'mode':'new','name':'任务甲','exploration_requirements':'合成合作要求','platforms':['web'],'seed_keywords':['合成入口']})
        self.second=request_run(self.files,{'mode':'new','name':'任务乙','platforms':['douyin']})
    def tearDown(self):self.tmp.cleanup()
    def test_read_only_context_uses_requested_project_and_preserves_files(self):
        before=self.files.path.read_bytes();context=task_context(self.files,self.first['id'])
        self.assertEqual(context['project']['id'],self.first['project_id'])
        self.assertEqual(context['project']['seed_keywords'],['合成入口'])
        self.assertEqual(context['request']['platforms'],['web'])
        self.assertEqual(context['next_action'],'start');self.assertIsNone(context['run'])
        self.assertEqual(self.files.path.read_bytes(),before)
    def test_saved_request_prompt_targets_exact_task_and_current_installation(self):
        prompt=self.first['execution_prompt']
        self.assertIn('python demo.py task '+self.first['id']+' --begin',prompt)
        self.assertIn(str(ROOT),prompt)
        self.assertIn(str(self.files.path.resolve()),prompt)
        self.assertIn('skills/search-opportunity/SKILL.md',prompt)
        self.assertIn('python demo.py task '+self.second['id']+' --begin',self.second['execution_prompt'])
        self.assertNotIn('execution_prompt',self.files.load()['requests'][0])
    def test_begin_resumes_same_round_and_selects_correct_project(self):
        begun=task_context(self.files,self.first['id'],begin=True)
        self.assertEqual(begun['next_action'],'resume');self.assertEqual(begun['run']['counts']['searches'],0)
        self.assertEqual(self.files.load()['active_project_id'],self.first['project_id'])
        select_project(self.files,self.second['project_id'])
        resumed=task_context(self.files,self.first['id'],begin=True)
        self.assertEqual(resumed['run']['id'],begun['run']['id'])
        self.assertEqual(len(self.files.load()['runs']),1)
        self.assertEqual(self.files.load()['active_project_id'],self.first['project_id'])
    def test_conflicting_task_cannot_be_started_or_silently_ended(self):
        active=task_context(self.files,self.first['id'],begin=True)
        before=self.files.path.read_bytes()
        context=task_context(self.files,self.second['id'])
        self.assertEqual(context['next_action'],'conflict');self.assertEqual(context['conflicting_run']['id'],active['run']['id'])
        with self.assertRaisesRegex(ValueError,active['run']['id']):task_context(self.files,self.second['id'],begin=True)
        self.assertEqual(self.files.path.read_bytes(),before)
    def test_finished_task_does_not_restart(self):
        begun=task_context(self.files,self.first['id'],begin=True)
        finish(self.files,begun['run']['id'],'仅用于隔离测试','interrupted','user_stopped')
        before=self.files.path.read_bytes();context=task_context(self.files,self.first['id'],begin=True)
        self.assertEqual(context['next_action'],'report');self.assertEqual(self.files.path.read_bytes(),before)
    def test_invalid_id_does_not_change_state(self):
        before=self.files.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'不存在'):task_context(self.files,'not-an-id',begin=True)
        self.assertEqual(self.files.path.read_bytes(),before)
    def test_cli_works_from_another_directory_and_is_idempotent(self):
        command=[sys.executable,'-X','utf8',str(ROOT/'demo.py'),'--data',str(self.files.path),'task',self.first['id'],'--begin']
        results=[]
        for _ in range(2):
            result=subprocess.run(command,cwd=self.tmp.name,capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);results.append(json.loads(result.stdout))
        self.assertEqual(results[0]['run']['id'],results[1]['run']['id'])
        self.assertEqual(results[0]['project']['name'],'任务甲')


if __name__=='__main__':unittest.main()
