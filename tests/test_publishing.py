"""Scenario-A invariants using isolated synthetic media and accounts; never real data."""
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from demo import Files,add_asset,make_server,now,public_state,request_run
from publishing import (CHECKS,approve_job,create_job,edit_job,generate_cover,package_zip,
                        record_execution,request_draft,view_job)

ACCOUNT="https://www.xiaohongshu.com/user/profile/aaaaaaaaaaaaaaaaaaaaaaaa"
ACCOUNT2="https://www.xiaohongshu.com/user/profile/bbbbbbbbbbbbbbbbbbbbbbbb"
POST="https://www.xiaohongshu.com/explore/cccccccccccccccccccccccc"


class PublishingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import imageio_ffmpeg
            from PIL import Image
        except ImportError as error:raise unittest.SkipTest("媒体渲染集成需要本机 Pillow 与 imageio-ffmpeg") from error
        cls.media_tmp=tempfile.TemporaryDirectory();cls.video=Path(cls.media_tmp.name)/"synthetic.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-nostdin","-hide_banner","-loglevel","error","-y","-f","lavfi",
                        "-i","color=c=teal:s=320x180:d=1","-c:v","libx264","-pix_fmt","yuv420p",str(cls.video)],
                       check=True,capture_output=True,timeout=20,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    @classmethod
    def tearDownClass(cls):cls.media_tmp.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.files=Files(self.root/"workspace.json")
        self.path=self.root/"fixture.mp4";self.path.write_bytes(self.video.read_bytes())
        self.asset=add_asset(self.files,{"path":str(self.path),"title":"合成成片"})
        self.job=create_job(self.files,{"asset_id":self.asset["id"]},now())
    def tearDown(self):self.tmp.cleanup()
    def latest(self):return next(j for j in self.files.load()["publication_jobs"] if j["id"]==self.job["id"])
    def edit(self,**kwargs):
        self.job=edit_job(self.files,{"id":self.job["id"],"expected_revision":self.latest()["revisions"][-1]["number"],**kwargs},now())
        return self.job
    def cover(self,headline="合成测试封面"):
        return generate_cover(self.files,{"id":self.job["id"],"expected_revision":self.latest()["revisions"][-1]["number"],
                                          "frame_seconds":0.2,"headline":headline,"subtitle":"仅供自动测试"},now())
    def ready(self):
        self.edit(title="合成标题",body="这是隔离测试的正文，不是真实发布建议。",tags=["#测试"],account_name="合成测试账号",account_url=ACCOUNT)
        self.cover()
        self.edit(checks={k:True for k in CHECKS})
        return self.latest()
    def approve(self):
        job=self.latest();r=job["revisions"][-1]
        return approve_job(self.files,{"id":job["id"],"expected_revision":r["number"],"revision_hash":r["hash"]},now())
    def execution(self,kind,**kwargs):
        return record_execution(self.files,{"id":self.job["id"],"expected_revision":self.latest()["revisions"][-1]["number"],
                                            "kind":kind,"note":"合成执行夹具，非真实平台活动",**kwargs},now())
    def draft(self):
        return request_draft(self.files,{"id":self.job["id"],"expected_revision":self.latest()["revisions"][-1]["number"]},now())
    def test_new_task_is_honest_and_repeated_creation_reuses_it(self):
        duplicate=create_job(self.files,{"asset_id":self.asset["id"]},now())
        self.assertEqual(duplicate["id"],self.job["id"])
        self.assertEqual(duplicate["request_status"],"waiting_codex")
        self.assertEqual(duplicate["revisions"][-1]["body"],"")
        self.assertEqual(view_job(self.files.load(),duplicate)["status"],"preparing")
    def test_original_media_is_unchanged_and_cover_is_real_png(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest();cover=self.cover()
        from PIL import Image
        with Image.open(cover["path"]) as image:self.assertEqual(image.size,(1080,1440));self.assertEqual(image.format,"PNG")
        self.assertTrue(Path(cover["frame_path"]).is_file())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        self.assertEqual(cover["asset_version"],self.asset["version"])
    def test_douyin_cover_uses_separate_portrait_template(self):
        xhs_id=self.job["id"]
        self.job=create_job(self.files,{"asset_id":self.asset["id"],"platform":"douyin"},now())
        cover=self.cover()
        from PIL import Image
        with Image.open(cover["path"]) as image:self.assertEqual(image.size,(1080,1920))
        self.assertNotEqual(self.job["id"],xhs_id)
        config=view_job(self.files.load(),self.latest())["platform_config"]
        self.assertEqual(config["name"],"抖音")
    def test_materials_complete_does_not_mean_confirmed_or_platform_draft_filled(self):
        self.edit(title="合成标题",body="合成正文",tags=["#测试"]);self.cover()
        view=view_job(self.files.load(),self.latest())
        self.assertTrue(view["local_package_ready"]);self.assertFalse(view["can_confirm"])
        self.assertEqual(view["status"],"needs_review");self.assertEqual(view["draft"]["status"],"not_filled")
        with self.assertRaises(ValueError):self.approve()
        evidence={"url":"https://creator.xiaohongshu.com/publish/publish?target=video","read_at":now(),
                  "excerpt":"合成规则夹具；只用于隔离测试","max_video_seconds":2,"max_video_bytes":100000000}
        self.edit(platform_evidence=evidence)
        row=next(r for r in view_job(self.files.load(),self.latest())["preflight"] if r["key"]=="upload_rules")
        self.assertEqual(row["status"],"pass")
        evidence["max_video_seconds"]=0.5;self.edit(platform_evidence=evidence)
        row=next(r for r in view_job(self.files.load(),self.latest())["preflight"] if r["key"]=="upload_rules")
        self.assertEqual(row["status"],"blocked")
    def test_zip_contains_exact_video_cover_copy_and_manifest(self):
        self.ready();job=self.latest();view=view_job(self.files.load(),job)
        with package_zip(self.files.load(),job) as stream:
            with zipfile.ZipFile(stream) as archive:
                self.assertEqual(archive.read("media/fixture.mp4"),self.path.read_bytes())
                self.assertEqual(archive.read("title.txt").decode(),view["current"]["title"])
                self.assertTrue(archive.read("cover.png").startswith(b"\x89PNG"))
                manifest=json.loads(archive.read("manifest.json"))
                self.assertFalse(manifest["approval_valid"]);self.assertEqual(manifest["draft"]["status"],"not_filled")
                self.assertEqual(manifest["revision_hash"],view["current"]["hash"])
        self.assertTrue((self.root/"发布准备.csv").exists())
    def test_stale_editor_cannot_overwrite_another_revision(self):
        number=self.latest()["revisions"][-1]["number"];self.edit(title="先保存的修改")
        with self.assertRaisesRegex(ValueError,"新版本"):
            edit_job(self.files,{"id":self.job["id"],"expected_revision":number,"title":"丢失更新"},now())
        self.assertEqual(self.latest()["revisions"][-1]["title"],"先保存的修改")
    def test_title_body_account_cover_and_schedule_change_invalidate_confirmation(self):
        for field,value in [("title","改动标题"),("body","改动正文"),("account_url",ACCOUNT2),("scheduled_at","2026-11-10T17:00:00+08:00")]:
            self.ready();self.approve();self.edit(**{field:value})
            view=view_job(self.files.load(),self.latest())
            self.assertFalse(view["approval_valid"],field);self.assertEqual(view["current"]["checks"],{})
        self.ready();self.approve();self.cover("另一张测试封面")
        self.assertFalse(view_job(self.files.load(),self.latest())["approval_valid"])
    def test_tampered_cover_and_changed_video_cannot_keep_confirmation(self):
        self.ready();self.approve();job=self.latest();cover=next(c for c in job["covers"] if c["id"]==job["revisions"][-1]["cover_id"])
        Path(cover["path"]).write_bytes(b"not a cover")
        self.assertFalse(view_job(self.files.load(),job)["approval_valid"])
        with self.assertRaises(ValueError):package_zip(self.files.load(),job)
    def test_confirmation_rehashes_media_even_if_size_and_timestamp_were_restored(self):
        self.ready();stat=self.path.stat();content=bytearray(self.path.read_bytes());content[-1]^=1;self.path.write_bytes(content)
        os.utime(self.path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,"内容已变化"):self.approve()
        with self.assertRaisesRegex(ValueError,"原片内容或版本发生变化"):package_zip(self.files.load(),self.latest())
    def test_request_is_version_bound_idempotent_and_does_not_upload(self):
        self.ready();self.approve();first=self.draft();second=self.draft()
        self.assertEqual(first["task_id"],second["task_id"]);self.assertEqual(first["execution"],"waiting_codex")
        self.assertEqual(view_job(self.files.load(),self.latest())["status"],"draft_requested")
        self.edit(body="保存了另一版正文")
        with self.assertRaises(ValueError):self.draft()
    def test_unknown_result_prevents_blind_retry_including_new_package(self):
        self.ready();self.approve();self.draft();self.execution("draft_unknown")
        with self.assertRaises(ValueError):self.draft()
        self.execution("unknown")
        newer=create_job(self.files,{"asset_id":self.asset["id"]},now())
        newer=edit_job(self.files,{"id":newer["id"],"expected_revision":1,"account_url":ACCOUNT},now())
        self.assertTrue(any(r["key"]=="uncertain_previous" for r in view_job(self.files.load(),newer)["preflight"]))
    def test_blocked_draft_has_only_one_bounded_retry(self):
        self.ready();self.approve();self.draft();self.execution("draft_blocked")
        self.assertEqual(self.draft()["attempts"],2);self.execution("draft_blocked")
        with self.assertRaisesRegex(ValueError,"两次"):self.draft()
    def test_filled_draft_needs_actual_evidence_and_matching_account(self):
        self.ready();self.approve();self.draft()
        with self.assertRaises(ValueError):self.execution("draft_filled",evidence={"source":"platform_ui","account_url":ACCOUNT})
        cover=Path(self.latest()["covers"][-1]["path"])
        with self.assertRaises(ValueError):self.execution("draft_filled",evidence={"source":"platform_ui","account_url":ACCOUNT2,"screenshot":str(cover)})
    def test_manual_publication_receipt_records_history_without_claiming_verification(self):
        self.ready();self.execution("published_reported",url=POST)
        view=view_job(self.files.load(),self.latest())
        self.assertEqual(view["status"],"published_reported")
        self.assertEqual(view["receipts"][-1]["source"],"manual_report")
        self.assertTrue(view["asset"]["published"])
        self.assertEqual(view["asset"]["publication_history"][-1]["asset_version"],self.asset["version"])
        with self.assertRaises(ValueError):self.edit(body="不能重写已发布版本")
        with self.assertRaises(ValueError):self.cover()
    def test_project_isolation_applies_to_jobs_covers_and_receipts(self):
        request_run(self.files,{"mode":"new","name":"另一个测试项目","direction":"测试","assets_brief":"没有素材"})
        self.assertEqual(public_state(self.files)["publications"],[])
        with self.assertRaises(ValueError):edit_job(self.files,{"id":self.job["id"],"expected_revision":1,"title":"越界"},now())
    def test_api_downloads_package_but_does_not_offer_fake_draft_completion(self):
        self.ready();server=make_server(self.files,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base="http://127.0.0.1:"+str(server.server_port)
        try:
            with urlopen(base+"/api/state") as response:token=json.loads(response.read())["csrf"]
            request=Request(base+"/api/publications/receipt",data=json.dumps({"id":self.job["id"],"kind":"draft_filled"}).encode(),
                            headers={"Content-Type":"application/json","X-Demo-Token":token})
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(error.exception.code,400)
            with urlopen(base+"/api/publication-package?id="+self.job["id"]) as response:
                self.assertEqual(response.headers["Content-Type"],"application/zip");self.assertTrue(response.read(4).startswith(b"PK"))
        finally:server.shutdown();server.server_close();thread.join()
