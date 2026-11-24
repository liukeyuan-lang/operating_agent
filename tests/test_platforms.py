"""Isolated multi-platform contract tests. No live data or search results."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from demo import Files,add_asset,add_source,canonical,finish,now,public_state,record,request_run,start_run
from platforms import account_url,content_url,detect_platform,platform_list,discovery_platform_list
from publishing import create_job,edit_job,record_execution
from research import record_check,record_snapshot
from workflow import coverage
from test_demo import packet
from test_planning import content_plan,mp4
from planning import save_plan

DY="https://www.douyin.com/video/7550615107627486523"
ACCOUNT="https://www.douyin.com/user/MS4wLjABAAAA_fixture"


class PlatformsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.files=Files(self.root/"workspace.json")
    def tearDown(self):self.tmp.cleanup()
    def test_url_identity_and_platform_mismatch(self):
        self.assertEqual(content_url("https://www.douyin.com/jingxuan?modal_id=7550615107627486523&foo=token"),DY)
        self.assertEqual(canonical(DY+"?tracking=1"),DY)
        self.assertEqual(detect_platform("https://douyin.com.evil.test/video/123"),"web")
        for url in [DY,"https://www.douyin.com/jingxuan","https://v.douyin.com/short/","https://www.douyin.com.evil.test/video/7550615107627486523"]:
            with self.assertRaises(ValueError):content_url(url,"xiaohongshu")
        self.assertEqual(account_url(ACCOUNT+"?tracking=x","douyin"),ACCOUNT)
        with self.assertRaises(ValueError):account_url(ACCOUNT,"xiaohongshu")
        self.assertEqual(platform_list(["小红书","dy","douyin"]),["xiaohongshu","douyin"])
    def test_xhs_profile_note_path_matches_same_note_identity(self):
        profile_note='https://www.xiaohongshu.com/user/profile/5c67ab69000000001202ead9/6ae9a8ba000000000e0366e4?xsec_token=fixture'
        expected='https://www.xiaohongshu.com/explore/6ae9a8ba000000000e0366e4'
        self.assertEqual(content_url(profile_note,'xiaohongshu'),expected)
        self.assertEqual(canonical(profile_note),expected)
        with self.assertRaises(ValueError):content_url('https://www.xiaohongshu.com/user/profile/5c67ab69000000001202ead9')
    def test_two_platform_request_and_coverage_need_real_platform_searches(self):
        req=request_run(self.files,{"mode":"continue","platforms":["xiaohongshu","douyin"]})
        run=start_run(self.files,request_id=req["id"])
        data={"id":"query","run_id":run["id"],"counts":{"searches":1},"queries":[{"query":"合成查询","direction":"合成方向","focus":"topics","reason":"隔离测试","channel":"xhs"}]}
        record(self.files,data)
        current=self.files.load()["runs"][-1]
        self.assertEqual(coverage(current)['achieved']['platforms'],1)
        self.assertEqual(coverage(current)['gaps'],{})
        data["id"]="douyin-query";data["queries"][0]["channel"]="douyin";record(self.files,data)
        self.assertEqual(coverage(self.files.load()["runs"][-1])["achieved"]["platforms"],2)
    def test_web_only_exploration_records_page_bodies_and_can_complete(self):
        self.assertEqual(discovery_platform_list(['网页搜索','web','dy']),['web','douyin'])
        with self.assertRaises(ValueError):platform_list(['web'])  # Never becomes a publishing destination.
        req=request_run(self.files,{'mode':'new','platforms':['web']})
        run=start_run(self.files,request_id=req['id'])
        record(self.files,{'id':'web-only-fixture','run_id':run['id'],
            'counts':{'searches':6,'post_reads':15,'source_checks':3},
            'queries':[{'query':'合成网页检索'+str(n),'channel':'web','reason':'隔离测试，非真实搜索'} for n in range(6)],
            'read_post_urls':['https://example.test/articles/'+str(n) for n in range(15)],
            'sources':[{'name':'合成公开来源'+str(n),'url':'https://example.test/organizers/'+str(n),
                'role':'organizer','reason':'隔离测试','checked_at':now()} for n in range(3)]})
        ended=finish(self.files,run['id'],'合成网页覆盖验收，不代表真实探索')
        self.assertTrue(ended['coverage']['sufficient']);self.assertEqual(ended['coverage']['achieved']['platforms'],1)
        state=public_state(self.files)
        self.assertEqual(state['current_project']['discovery_platforms'],['web'])
        self.assertIn({'id':'web','name':'网页搜索','channel':'web'},state['discovery_platform_catalog'])
        self.assertNotIn('web',[p['id'] for p in state['platform_catalog']])
        with self.assertRaises(ValueError):create_job(self.files,{'platform':'web'},now())
    def test_web_search_counts_only_for_selected_web_coverage(self):
        req=request_run(self.files,{'mode':'new','platforms':['web','xiaohongshu']})
        run=start_run(self.files,request_id=req['id'])
        record(self.files,{'id':'web-query','run_id':run['id'],'counts':{'searches':1},
            'queries':[{'query':'合成搜索','direction':'合成方向','reason':'隔离测试','channel':'web'}]})
        self.assertEqual(coverage(self.files.load()['runs'][-1])['achieved']['platforms'],1)
        self.assertEqual(coverage(self.files.load()['runs'][-1])['gaps'],{})
        self.assertEqual(self.files.load()['runs'][-1]['counts']['post_reads'],0)
    def test_web_body_cannot_count_when_web_is_unselected(self):
        run=start_run(self.files)
        with self.assertRaises(ValueError):record(self.files,{'id':'unselected-web','run_id':run['id'],
            'counts':{'post_reads':1},'read_post_urls':['https://example.test/article']})
        self.assertEqual(self.files.load()['runs'][-1]['counts']['post_reads'],0)
    def test_douyin_post_and_peer_memory_keep_identity_across_packets(self):
        req=request_run(self.files,{"mode":"continue","platforms":["douyin"]});run=start_run(self.files,request_id=req["id"])
        p=packet(run);p["items"][0]["url"]=DY;p["sources"]=[{"name":"合成同行","url":ACCOUNT,"role":"peer","reason":"合成观察","seen_posts":[DY],"checked_at":now()}]
        record(self.files,p);p["id"]="second";p["items"][0]["url"]=DY+"?tracker=1";record(self.files,p)
        state=public_state(self.files)
        self.assertEqual(len(state["items"]),1);self.assertEqual(state["items"][0]["platform"],"douyin")
        self.assertEqual(state["sources"][0]["seen_posts"],[DY]);self.assertEqual(state["runs"][-1]["new_peer_posts"],1)
    def test_unselected_platform_read_is_rejected_atomically(self):
        run=start_run(self.files);p=packet(run);p["items"][0]["url"]=DY
        with self.assertRaises(ValueError):record(self.files,p)
        self.assertEqual(self.files.load()["items"],[])
    def test_manual_source_exports_platform(self):
        row=add_source(self.files,{"name":"合成同行","url":ACCOUNT,"role":"peer","reason":"测试"})
        self.assertEqual(row["platform"],"douyin")
        self.assertIn("抖音",(self.root/"观察清单.csv").read_text(encoding="utf-8-sig"))
    def test_web_index_sample_never_counts_as_read_or_heat(self):
        sample={"platform":"douyin","source_type":"web_index","query":"合成查询","sort":"搜索引擎相关性","time_window":"未知","scope_note":"合成夹具，仅摘要，不是平台原帖", "items":[{"url":DY,"title":"合成摘要"}]}
        saved=record_snapshot(self.files,sample,now())
        self.assertIsNone(saved["items"][0]["metrics"]["likes"])
        self.assertFalse(saved["items"][0]["body_read"])
        self.assertEqual(public_state(self.files)["runs"],[])
        invalid=copy.deepcopy(sample);invalid["items"][0]["metrics"]={"likes":10}
        with self.assertRaises(ValueError):record_snapshot(self.files,invalid,now())
        invalid=copy.deepcopy(sample);invalid["items"][0]["body_read"]=True
        with self.assertRaises(ValueError):record_snapshot(self.files,invalid,now())
        self.assertIn("未核实",(self.root/"平台观察样本.csv").read_text(encoding="utf-8-sig"))
    def test_capability_check_needs_evidence_and_remains_project_scoped(self):
        with self.assertRaises(ValueError):record_check(self.files,{"platform":"douyin","capability":"search","status":"verified","note":"没有证据"},now())
        record_check(self.files,{"platform":"douyin","capability":"search","status":"blocked","note":"合成连接故障"},now())
        dy=next(p for p in public_state(self.files)["platform_catalog"] if p["id"]=="douyin")
        self.assertEqual(dy["checks"][0]["status"],"blocked")
        request_run(self.files,{"mode":"new","name":"第二项目","direction":"合成方向","assets_brief":"无素材"})
        dy=next(p for p in public_state(self.files)["platform_catalog"] if p["id"]=="douyin")
        self.assertEqual(dy["checks"][0]["status"],"untested")
    def test_separate_publication_packages_and_receipts(self):
        a=add_asset(self.files,{"path":str(mp4(self.root/"fixture.mp4"))})
        xhs=create_job(self.files,{"asset_id":a["id"]},now());dy=create_job(self.files,{"asset_id":a["id"],"platform":"douyin"},now())
        self.assertNotEqual(xhs["id"],dy["id"])
        dy=edit_job(self.files,{"id":dy["id"],"expected_revision":1,"title":"合成标题","body":"抖音独立文案","account_url":ACCOUNT},now())
        with self.assertRaises(ValueError):record_execution(self.files,{"id":dy["id"],"expected_revision":2,"kind":"published_reported","note":"测试跨平台拒绝","url":"https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa"},now())
        self.assertEqual(self.files.load()["publication_jobs"][0]["revisions"][-1]["body"],"")
        saved=record_execution(self.files,{"id":dy["id"],"expected_revision":2,"kind":"published_reported","note":"合成人工回执","url":DY},now())
        self.assertEqual(saved["receipts"][0]["url"],DY)
    def test_cross_platform_action_reuses_brief_not_copy_and_does_not_hijack_card(self):
        add_asset(self.files,{"path":str(mp4(self.root/"fixture.mp4"))})
        plan=content_plan(self.files);plan["actions"][0]["materials"]=[]
        asset=self.files.load()["projects"][0]["asset_references"][-1]
        plan["actions"][0]["materials"]=[{"asset_id":asset["id"],"version":asset["version"]}]
        saved=save_plan(self.files,plan,now());a=saved["actions"][0]
        xhs=create_job(self.files,{"plan_id":saved["id"],"action_id":a["id"]},now())
        dy=create_job(self.files,{"plan_id":saved["id"],"action_id":a["id"],"platform":"douyin"},now())
        self.assertEqual(dy["revisions"][-1]["body"],"")
        self.assertEqual(dy["request_status"],"waiting_codex")
        self.assertEqual(public_state(self.files)["weekly_plan"]["actions"][0]["publication_id"],xhs["id"])
    def test_ui_components_render_platform_specific_fields(self):
        node=shutil.which("node")
        if not node:self.skipTest("Node unavailable for local JS component checks")
        asset=add_asset(self.files,{"path":str(mp4(self.root/"fixture.mp4"))})
        create_job(self.files,{"asset_id":asset["id"],"platform":"douyin"},now())
        result=subprocess.run([node,"tests/ui_render.cjs"],input=json.dumps(public_state(self.files)),text=True,encoding="utf-8",capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
