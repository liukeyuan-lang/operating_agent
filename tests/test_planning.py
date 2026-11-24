"""Reproducible scenario-B checks. Synthetic evidence stays in isolated files."""
import copy
import json
import struct
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from demo import Files, add_asset, make_server, now, public_state, record, request_run, start_run
from media import inspect_mp4, local_available
from planning import next_week, package_markdown, review_action, save_plan, signal_state
from workflow import TZ, coverage, profile_digest, project
from test_demo import packet


def assessment():
    return {k:{"status":"insufficient", "note":"合成夹具：本维度证据不足，不作肯定结论"}
            for k in ("topics", "peers", "opportunities", "assets")}


def no_action_plan(files, run_ids=None):
    p=project(files.load())
    return {"project_id":p["id"], "profile_digest":profile_digest(p), "week_start":next_week(),
            "assessment":assessment(), "run_ids":run_ids or [], "actions":[],
            "no_action_reason":"合成夹具：暂无值得新增投入的任务"}


def content_plan(files, run_ids=None):
    payload=no_action_plan(files,run_ids)
    p=project(files.load());a=p["asset_references"][0]
    payload["actions"]=[{"key":"fixture-content", "kind":"content", "title":"合成内容行动",
        "scheduled_at":next_week()+"T15:00:00+08:00", "reason":"已有素材仍可形成内容任务，即使没有可报名活动",
        "basis":[{"type":"project","id":p["id"]}],
        "materials":[{"asset_id":a["id"],"version":a["version"]}], "effort_hours":{"min":1,"max":2},
        "steps":["准备"],"remaining_work":["选择媒体文件并人工填写草稿"],"confirmations":["确认确切素材和账号"],
        "risks":["版权未知"],"reuse":["项目介绍与作品案例"],
        "package":{"platform":"小红书","title":"合成标题","body":"合成正文，绝非真实推荐",
                   "cover_brief":"封面方案尚未出图","tags":["#合成测试"]}}]
    return payload


def mp4(path):
    def box(kind, body):return struct.pack(">I4s",len(body)+8,kind)+body
    mvhd=b"\0"*12+struct.pack(">II",1000,12500)
    tkhd=b"\0"*8+struct.pack(">II",854*65536,480*65536)
    hdlr=b"\0"*8+b"vide"
    path.write_bytes(box(b"ftyp",b"isom")+box(b"moov",box(b"mvhd",mvhd)+box(b"trak",box(b"tkhd",tkhd)+box(b"mdia",box(b"hdlr",hdlr)))))
    return path


class PlanningTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.files=Files(Path(self.tmp.name)/"workspace.json")
        # Independent of the sender's personal config and the blank delivery template.
        def seed(data):
            project(data)["asset_references"]=[{"id":"fixture-reference","title":"合成参考素材",
                "type":"video","version":"fixture-v1","locator":"https://example.test/video",
                "availability":"reference_only","rights":"unknown","published":True,"specs":{}}]
        self.files.change(seed)
    def tearDown(self):self.tmp.cleanup()
    def test_no_activity_result_can_still_produce_prepared_content_action(self):
        save_plan(self.files,content_plan(self.files),now())
        view=public_state(self.files)
        self.assertEqual(view["results"],[])
        a=view["weekly_plan"]["actions"][0]
        self.assertIn("媒体文件 0/1",a["preparation"])
        self.assertIn("平台草稿未填写",a["preparation"])
        self.assertIn("合成正文",package_markdown(view["weekly_plan"],a))
        self.assertTrue((Path(self.tmp.name)/"每周行动卡.csv").exists())
    def test_unqualified_lead_is_allowed_as_verification_not_participation(self):
        run=start_run(self.files);record(self.files,packet(run))
        payload=content_plan(self.files);a=payload["actions"][0]
        a["basis"]=[{"type":"item","id":self.files.load()["items"][0]["id"]}]
        a["package"]["brief"]="先核验资格，不提交"
        a["kind"]="opportunity"
        with self.assertRaisesRegex(ValueError,"不可直接参与"):save_plan(self.files,payload,now())
        a["kind"]="verify";save_plan(self.files,payload,now())
        self.assertEqual(public_state(self.files)["weekly_plan"]["actions"][0]["kind"],"verify")
    def test_action_requires_broad_assessment_and_actual_package(self):
        payload=content_plan(self.files);payload["assessment"].pop("topics")
        with self.assertRaises(ValueError):save_plan(self.files,payload,now())
        payload=content_plan(self.files);payload["actions"][0]["package"].pop("body")
        with self.assertRaises(ValueError):save_plan(self.files,payload,now())
        payload=content_plan(self.files);payload["actions"][0]["package"]["platform_draft"]="filled"
        with self.assertRaisesRegex(ValueError,"未接入"):save_plan(self.files,payload,now())
    def test_file_provided_is_not_the_same_as_copyright_cleared(self):
        path=mp4(Path(self.tmp.name)/"fixture.mp4")
        asset=add_asset(self.files,{"path":str(path)})
        self.assertEqual(asset["specs"]["duration_seconds"],12.5)
        self.assertEqual(asset["specs"]["width"],854)
        self.assertTrue(local_available(asset))
        self.assertEqual(asset["rights"],"unknown")
        payload=content_plan(self.files)
        payload["actions"][0]["materials"]=[{"asset_id":asset["id"],"version":asset["version"]}]
        save_plan(self.files,payload,now())
        view=public_state(self.files);action=view["weekly_plan"]["actions"][0]
        self.assertIn("媒体文件 1/1",action["preparation"])
        self.assertIn("授权待确认",action["preparation"])
        path.write_bytes(path.read_bytes()+b"changed")
        action=public_state(self.files)["weekly_plan"]["actions"][0]
        self.assertFalse(action["material_details"][0]["file_available"])
        self.assertTrue(action["issues"])
    def test_ordinary_peer_post_cannot_be_called_platform_hot_topic(self):
        run=start_run(self.files)
        signal={"key":"fixture-topic","kind":"topic","title":"合成选题","summary":"单篇帖子",
                "fit_reason":"主题相关，但热度未知","evidence":[{"title":"测试原帖","url":"https://example.test/post",
                "read_at":now(),"excerpt":"a visible sentence"}]}
        record(self.files,{"id":"topic","run_id":run["id"],"signals":[signal]})
        self.assertIn("热度未证实",public_state(self.files)["signals"][0]["evidence_state"])
        signal["heat"]={"status":"platform_ranked","rank":1,"source_url":"https://example.test/post","evidence":"visible"}
        with self.assertRaisesRegex(ValueError,"榜单"):record(self.files,{"id":"fake-heat","run_id":run["id"],"signals":[signal]})
        self.assertEqual(len(self.files.load()["signals"]),1)
    def test_hot_evidence_expires_instead_of_remaining_hot_forever(self):
        signal={"kind":"topic","evidence":[{"url":"https://example.test/rank","read_at":"2026-01-01T12:00:00+08:00"}],
                "heat":{"status":"platform_ranked","source_url":"https://example.test/rank"}}
        self.assertEqual(signal_state(signal,"2026-01-02T12:00:00+08:00"),"平台榜单观察")
        self.assertEqual(signal_state(signal,"2026-01-09T12:00:00+08:00"),"榜单证据需更新")
        signal["evidence"].append({"url":"https://example.test/rank","read_at":"2026-01-09T12:00:00+08:00"})
        self.assertEqual(signal_state(signal,"2026-01-09T13:00:00+08:00"),"平台榜单观察")
    def test_same_decision_keeps_human_feedback_across_plan_revisions(self):
        first=save_plan(self.files,content_plan(self.files),now())
        review_action(self.files,{"plan_id":first["id"],"action_id":first["actions"][0]["id"],
                                  "status":"deferred","note":"合成偏好：本周没有工时"},now())
        second=save_plan(self.files,content_plan(self.files),now())
        self.assertEqual(second["actions"][0]["review"]["status"],"deferred")
        self.assertIn("工时",second["actions"][0]["review"]["note"])
    def test_plans_topics_and_assets_do_not_leak_into_new_project(self):
        plan=save_plan(self.files,content_plan(self.files),now())
        request_run(self.files,{"mode":"new","name":"不同项目","direction":"合成","assets_brief":"空"})
        view=public_state(self.files)
        self.assertIsNone(view["weekly_plan"]);self.assertEqual(view["signals"],[]);self.assertEqual(view["assets"],[])
        with self.assertRaises(ValueError):review_action(self.files,{"plan_id":plan["id"],"action_id":plan["actions"][0]["id"],"status":"kept"},now())
    def test_project_change_marks_old_plan_for_reassessment(self):
        save_plan(self.files,content_plan(self.files),now())
        request_run(self.files,{"mode":"continue","resources_brief":"合成：本周0小时"})
        self.assertTrue(public_state(self.files)["weekly_plan"]["actions"][0]["issues"])
        self.assertEqual(project(self.files.load())['asset_references'],[])
        view=public_state(self.files)
        self.assertEqual(view["weekly_plan"]["actions"][0]["material_details"][0]["title"],"已移除素材")
    def test_legacy_focus_areas_are_observations_not_completion_targets(self):
        run=start_run(self.files)
        run['scenario']='weekly_planning';run['targets']['focus_areas']=3
        run["search_queries"]=[{"channel":"xhs","query":str(i),"focus":"opportunities"} for i in range(6)]
        self.assertEqual(coverage(run)["achieved"]["focus_areas"],1)
        self.assertEqual(coverage(run)["gaps"],{})
    def test_media_stream_is_scoped_and_reads_only_registered_asset(self):
        asset=add_asset(self.files,{"path":str(mp4(Path(self.tmp.name)/"fixture.mp4"))})
        plan=save_plan(self.files,content_plan(self.files),now())
        server=make_server(self.files,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base="http://127.0.0.1:"+str(server.server_port)
        try:
            with urlopen(base+"/api/state") as response:token=json.loads(response.read())["csrf"]
            bad_path=Request(base+"/api/assets",data=json.dumps({"path":str(Path(self.tmp.name)/"missing.mp4")}).encode(),
                             headers={"Content-Type":"application/json","X-Demo-Token":token})
            with self.assertRaises(HTTPError) as error:urlopen(bad_path)
            self.assertEqual(error.exception.code,400)
            with urlopen(Request(base+"/api/media/"+asset["id"],headers={"Range":"bytes=0-7"})) as response:
                self.assertEqual(response.status,206);self.assertEqual(len(response.read()),8)
            with self.assertRaises(HTTPError):urlopen(base+"/api/media/not-registered")
            with urlopen(base+"/api/action-package?plan_id="+plan["id"]+"&action_id="+plan["actions"][0]["id"]) as response:
                self.assertIn("合成正文",response.read().decode())
        finally:server.shutdown();server.server_close();thread.join()
