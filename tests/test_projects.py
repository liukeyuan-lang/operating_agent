"""Project isolation and strict result qualification; all data is synthetic."""
import copy
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path

from demo import Files,finish,now,public_state,record,request_run,select_project,start_run
from workflow import GATES,REQUIRED,classify,coverage,profile_digest,project
from planning import save_plan
from test_planning import no_action_plan
from test_demo import item,packet


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.files=Files(Path(self.tmp.name)/"workspace.json")
    def tearDown(self):self.tmp.cleanup()
    def new_project(self,name):
        return request_run(self.files,{"mode":"new","name":name,"direction":"合成测试方向",
                                      "assets_brief":"合成测试资产，已确认权属与规格","resources_brief":"测试资源"})
    def verified(self):
        p=project(self.files.load());doc={"id":"official","url":"https://example.test/call","title":"合成官方",
              "authority_basis":"测试夹具","read_at":now(),"excerpt":"fixture evidence"}
        obj=item();obj["official_sources"]=[doc]
        obj["facts"]={k:{"value":"已核对","status":"confirmed","source_id":"official","evidence":"fixture evidence"} for k in REQUIRED}
        obj["facts"]["deadline"]["at"]=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
        obj["facts"]["open_status"]["value"]="open";obj["facts"]["ai_policy"]["allowed"]=True
        obj["participation"]={"profile_digest":profile_digest(p),"checked_at":now(),
                             **{g:{"status":"pass","reason":"合成夹具核验已通过"} for g in GATES}}
        return obj,p
    def test_new_project_starts_empty_and_continuation_reuses_same_project(self):
        first=start_run(self.files);record(self.files,packet(first))
        finish(self.files,first["id"],"fixture","interrupted","user_stopped")
        original=self.files.load()["active_project_id"]
        new=self.new_project("第二个独立项目")
        self.assertEqual(public_state(self.files)["items"],[])
        self.assertEqual(public_state(self.files)["assets"],[])
        second=start_run(self.files,request_id=new["id"]);record(self.files,packet(second))
        finish(self.files,second["id"],"fixture","interrupted","user_stopped")
        self.assertEqual(len(self.files.load()["items"]),2)
        select_project(self.files,original)
        self.assertEqual(len(public_state(self.files)["items"]),1)
        req=request_run(self.files,{"mode":"continue","project_id":original})
        third=start_run(self.files,request_id=req["id"])
        self.assertEqual(third["project_id"],first["project_id"])
        self.assertEqual(len(public_state(self.files)["runs"]),2)
    def test_project_change_invalidates_old_participation(self):
        obj,p=self.verified();self.assertEqual(classify(obj,p)[0],"result")
        changed={**p,"assets_brief":"新素材，权属尚不清楚"}
        self.assertEqual(classify(obj,changed)[0],"lead")
    def test_only_live_qualified_matches_are_results(self):
        obj,p=self.verified()
        self.assertEqual(classify(obj,p)[0],"result")
        for modification,expected in [
            (lambda o:o.update(historical=True),"history"),
            (lambda o:o["facts"]["deadline"].update(at="2020-01-01T12:00:00+08:00"),"excluded"),
            (lambda o:o["facts"]["open_status"].update(value="closed"),"excluded"),
            (lambda o:o["facts"]["ai_policy"].update(allowed=False),"excluded"),
            (lambda o:o["facts"]["fees"].update(status="uncertain"),"lead"),
            (lambda o:o["participation"]["rights_clearance"].update(status="unknown"),"lead"),
            (lambda o:o["participation"]["eligibility"].update(status="fail"),"excluded")]:
            variant=copy.deepcopy(obj);modification(variant)
            self.assertEqual(classify(variant,p)[0],expected)
    def test_official_page_alone_cannot_be_promoted_to_result(self):
        obj,p=self.verified();obj.pop("participation")
        self.assertEqual(classify(obj,p)[0],"lead")
    def test_explicit_rolling_open_call_does_not_need_invented_deadline(self):
        obj,p=self.verified()
        obj["facts"]["deadline"].pop("at")
        obj["facts"]["deadline"].update(kind="rolling",value="明确滚动征集，无固定截止")
        self.assertEqual(classify(obj,p)[0],"result")
        obj["facts"]["open_status"]["value"]="closed"
        self.assertEqual(classify(obj,p)[0],"excluded")
    def test_expired_evidence_falls_back_to_lead(self):
        obj,p=self.verified();obj["official_sources"][0]["read_at"]="2020-01-01T12:00:00+08:00"
        self.assertEqual(classify(obj,p)[0],"lead")
    def test_completion_still_requires_assessment_without_quantity_floors(self):
        run=start_run(self.files);record(self.files,packet(run))
        with self.assertRaises(ValueError):finish(self.files,run["id"],"done")
        with self.assertRaises(ValueError):finish(self.files,run["id"],"time","partial","time_budget")
        ended=finish(self.files,run["id"],"explicit user stop","interrupted","user_stopped")
        self.assertEqual(ended["coverage"]["targets"],{})
    def test_complete_after_target_coverage_is_reached(self):
        run=start_run(self.files)
        pack={"id":"coverage","run_id":run["id"],"counts":{"searches":6,"post_reads":15,"source_checks":3},
              "read_post_urls":["https://www.xiaohongshu.com/explore/"+format(n,"024x") for n in range(15)],
              "queries":[{"query":"query"+str(n),"channel":"xhs","reason":"合成测试"} for n in range(6)],
              "sources":[{"name":"测试同行"+str(n),"url":"https://example.test/peer/"+str(n),"role":"peer",
                          "reason":"测试检查","checked_at":now()} for n in range(3)]}
        record(self.files,pack)
        ended=finish(self.files,run["id"],"fixture complete")
        self.assertTrue(ended["coverage"]["sufficient"])
        self.assertEqual(self.files.load()['weekly_plans'],[])
        self.assertNotIn('directions',ended['coverage']['targets'])
        self.assertNotIn('directions',ended['coverage']['achieved'])
    def test_legacy_direction_quota_does_not_reappear_on_resume(self):
        run=start_run(self.files)
        legacy=copy.deepcopy(run);legacy['targets']['directions']=999
        self.assertNotIn('directions',coverage(legacy)['targets'])
        def restore_old_fields(data):
            data['runs'][0]['targets']['directions']=999
            data['runs'][0]['coverage_directions']=['旧分类']
        self.files.change(restore_old_fields)
        resumed=self.files.load()['runs'][0]
        self.assertNotIn('directions',resumed['targets'])
        self.assertNotIn('coverage_directions',resumed)
        self.assertEqual(resumed['targets'],{})
    def test_legacy_query_field_is_optional_and_replay_stays_idempotent(self):
        run=start_run(self.files)
        payload={'id':'legacy-query','run_id':run['id'],'counts':{'searches':1},
                 'queries':[{'query':'合成搜索','direction':'旧分类','channel':'xhs','reason':'隔离测试'}]}
        original=copy.deepcopy(payload)
        record(self.files,payload);self.assertEqual(record(self.files,payload)['status'],'already_saved')
        self.assertEqual(payload,original)
        current=self.files.load()['runs'][0]
        self.assertEqual(current['counts']['searches'],1)
        self.assertNotIn('direction',current['search_queries'][0])
    def test_low_yield_does_not_require_labeling_search_categories(self):
        run=start_run(self.files)
        record(self.files,{'id':'low-yield-without-categories','run_id':run['id'],
            'counts':{'searches':4,'post_reads':8},
            'queries':[{'query':'合成检索'+str(n),'channel':'xhs','reason':'隔离测试'} for n in range(4)],
            'read_post_urls':['https://www.xiaohongshu.com/explore/'+format(n,'024x') for n in range(8)]})
        ended=finish(self.files,run['id'],'合成测试：已记录低收益依据','partial','low_yield')
        self.assertEqual(ended['stop_reason'],'low_yield')
    def test_repeated_queries_and_pages_are_not_unique_observations(self):
        run=start_run(self.files)
        pack={"id":"repeats","run_id":run["id"],"counts":{"searches":6,"post_reads":15,"source_checks":3},
              "read_post_urls":[item()["url"]]*15,
              "queries":[{"query":"same query","direction":"方向"+str(n%3),"focus":"opportunities","channel":"xhs","reason":"测试重复"} for n in range(6)],
              "sources":[{"name":"同一同行","url":"https://example.test/peer/one","role":"peer",
                          "reason":"测试检查","checked_at":now()} for n in range(3)]}
        record(self.files,pack)
        report=coverage(self.files.load()['runs'][0])
        self.assertEqual(report['achieved']['searches'],1)
        self.assertEqual(report['achieved']['post_reads'],1)
        self.assertEqual(report['achieved']['source_checks'],1)
        self.assertEqual(self.files.load()['runs'][0]['counts']['searches'],6)
    def test_results_and_leads_export_separately(self):
        run=start_run(self.files);obj,_=self.verified()
        record(self.files,{"id":"result","run_id":run["id"],"items":[obj]})
        view=public_state(self.files)
        self.assertEqual(len(view["results"]),1);self.assertEqual(len(view["leads"]),0)
        self.assertTrue((Path(self.tmp.name)/"可参加结果.csv").exists())
        self.assertTrue((Path(self.tmp.name)/"待核验线索.csv").exists())
    def test_input_is_project_and_materials_not_a_required_keyword(self):
        req=self.new_project("项目输入测试")
        self.assertIn("profile_snapshot",req)
        self.assertNotIn("search_topic",req)
        with self.assertRaises(ValueError):request_run(self.files,"人工填写关键词")
