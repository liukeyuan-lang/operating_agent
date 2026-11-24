"""Synthetic verification tests, never touch business records."""
import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from demo import Files,now,record,record_verification,request_run,start_run,public_state,finish
from verification import assess,team_input,refresh_checks
from workflow import profile_digest,project
from test_demo import packet

class VerificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.files=Files(Path(self.tmp.name)/'state.json')
    def tearDown(self):self.tmp.cleanup()
    def test_team_fields_persist_zero_values_unknown_and_project_isolation(self):
        request_run(self.files,{'mode':'continue','team_name':'合成团队','team_country':'中国','team_applicant_type':'team','team_budget_cny':'0','team_can_travel':'none'})
        first=project(self.files.load());self.assertEqual(first['team_profile']['budget_cny'],0)
        digest=profile_digest(first)
        request_run(self.files,{'mode':'continue','team_country':'法国'})
        self.assertNotEqual(profile_digest(project(self.files.load())),digest)
        request_run(self.files,{'mode':'new','name':'独立项目','direction':'测试','assets_brief':'未知'})
        self.assertEqual(project(self.files.load())['team_profile'],{})
    def test_invalid_team_does_not_write(self):
        for payload in [{'team_budget_cny':'NaN'},{'team_minimum_age':'-1'},{'team_minimum_age':'18.5'},{'team_can_travel':'yes'}]:
            with self.assertRaises(ValueError):request_run(self.files,{'mode':'continue',**payload})
        self.assertFalse(self.files.path.exists())
    def fixture(self):
        p=copy.deepcopy(project(self.files.load()));p['team_profile']={'country':'中国','applicant_type':'team','minimum_age':21,'can_travel':'none'}
        i={'official_sources':[{'id':'doc','excerpt':'合成完整条件','read_at':now()}],
           'facts':{'eligibility':{'status':'confirmed','source_id':'doc','evidence':'合成完整条件',
               'requirements':{'complete':True,'countries':['*'],'applicant_types':['team'],'minimum_age':18}}}}
        return i,p
    def test_official_eligibility_compared_and_missing_profile_stays_unknown(self):
        i,p=self.fixture();self.assertEqual(assess(i,p,now())['eligibility']['status'],'pass')
        p['team_profile']['minimum_age']=None;self.assertEqual(assess(i,p,now())['eligibility']['status'],'unknown')
        p['team_profile']['minimum_age']=15;self.assertEqual(assess(i,p,now())['eligibility']['status'],'fail')
        i['official_sources'][0]['read_at']=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
        self.assertEqual(assess(i,p,now())['eligibility']['status'],'unknown')
    def test_material_spec_pass_does_not_claim_complete_content_eligibility(self):
        i,p=self.fixture();p['asset_references']=[{'availability':'local','locator':'clip.mp4','specs':{'width':1920,'height':1080}}]
        i['facts']['formats']={'status':'confirmed','source_id':'doc','evidence':'合成完整条件','requirements':{'complete':True,'min_width':1920,'min_height':1080}}
        self.assertEqual(assess(i,p,now())['asset_fit']['status'],'unknown')
        p['asset_references'][0]['specs']['width']=854
        self.assertEqual(assess(i,p,now())['asset_fit']['status'],'fail')
    def test_rechecking_does_not_extend_agent_evidence_lifetime(self):
        i,p=self.fixture();at=(datetime.now(timezone.utc)-timedelta(days=6)).isoformat()
        i['participation']={'profile_digest':profile_digest(p),'checked_at':at,'asset_fit':{'status':'pass','reason':'合成'}}
        checked=assess(i,p,now());self.assertEqual(checked['checked_at'],at)
        i['participation']=checked
        future=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        self.assertEqual(assess(i,p,future)['asset_fit']['status'],'unknown')
    def test_verification_receipt_is_scoped_version_bound_and_requires_actual_attempt(self):
        run=start_run(self.files);record(self.files,packet(run));i=self.files.load()['items'][0]
        payload={'id':i['id'],'profile_digest':profile_digest(project(self.files.load())),'attempt':{'urls':[i['url']],'note':'合成访问失败','blocked':True}}
        with self.assertRaises(ValueError):record_verification(self.files,{**payload,'profile_digest':'old'})
        with self.assertRaises(ValueError):record_verification(self.files,{**payload,'attempt':{}})
        result=record_verification(self.files,payload)
        self.assertEqual(result['verification']['status'],'blocked')
        self.assertEqual(public_state(self.files)['results'],[])
        self.assertTrue((self.files.path.parent/'机会核验.csv').exists())
    def test_new_ui_run_cannot_finish_without_checking_every_candidate(self):
        req=request_run(self.files,{'mode':'continue','auto_verify':True})
        run=start_run(self.files,request_id=req['id']);record(self.files,packet(run))
        # Isolate the verification completion gate from breadth/planning gates.
        def isolate(data):
            data['runs'][0]['legacy_demo']=True;data['runs'][0]['scenario']='fixture'
        self.files.change(isolate)
        with self.assertRaisesRegex(ValueError,'逐个查证'):finish(self.files,run['id'],'合成结束')
        i=self.files.load()['items'][0]
        record_verification(self.files,{'id':i['id'],'profile_digest':profile_digest(project(self.files.load())),
            'attempt':{'urls':[i['url']],'note':'合成访问受阻，未取得原始规则','blocked':True}})
        self.assertEqual(finish(self.files,run['id'],'保留受阻原因')['status'],'completed')
    def test_official_rule_change_invalidates_previous_agent_pass(self):
        i,p=self.fixture()
        i['participation']={'profile_digest':profile_digest(p),'checked_at':now(),'asset_fit':{'status':'pass','reason':'先前规则'}}
        i['participation']=assess(i,p,now())
        i['facts']['new_rule']={'status':'uncertain'}
        self.assertEqual(assess(i,p,now())['asset_fit']['status'],'unknown')
    def test_known_official_fee_over_budget_fails_without_treating_unknown_cost_as_free(self):
        i,p=self.fixture();p['team_profile']['budget_cny']=0
        i['facts']['fees']={'status':'confirmed','source_id':'doc','evidence':'合成完整条件','requirements':{'minimum_cost_cny':100}}
        self.assertEqual(assess(i,p,now())['resource_fit']['status'],'fail')
        p['team_profile']['budget_cny']=1000
        self.assertEqual(assess(i,p,now())['resource_fit']['status'],'unknown')

if __name__=='__main__':unittest.main()
