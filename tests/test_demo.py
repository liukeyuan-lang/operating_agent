"""Isolated synthetic tests: never write test records to the real workspace."""
import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from demo import (Files,add_source,canonical,evidence_state,finish,make_server,
                  now,record,request_run,set_review,start_run,unknowns)


def item():
    return {"title":"合成测试：互动艺术征集","url":"https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
            "fit":"strong","fit_reason":"仅为自动测试的虚构内容，不是真实机会",
            "summary":"fixture","read_at":now(),"discovery_path":[{"label":"合成种子","reason":"测试动态路径"}]}


def packet(run,number="one"):
    return {"id":number,"run_id":run["id"],"items":[item()],"counts":{"post_reads":1},
            "followups":[{"target":"合成新机构","kind":"official","reason":"从当前帖子而非起始关键词发现"}]}


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.files=Files(Path(self.tmp.name)/"workspace.json")
        self.run=start_run(self.files,"合成测试查询")
    def tearDown(self):
        self.tmp.cleanup()
    def test_files_and_csv_are_readable_without_database(self):
        record(self.files,packet(self.run))
        self.assertEqual(len(self.files.load()["items"]),1)
        self.assertTrue((Path(self.tmp.name)/"机会清单.csv").exists())
        self.assertTrue(self.files.path.with_suffix(".json.bak").exists())
        self.assertFalse(list(Path(self.tmp.name).glob("*.sqlite*")))
    def test_canonical_xhs_alias_and_tracking(self):
        self.assertEqual(canonical("https://www.xiaohongshu.com/search_result/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=secret"),
                         canonical(item()["url"]))
        with self.assertRaises(ValueError): canonical("javascript:alert(1)")
    def test_retry_is_idempotent_and_different_payload_rejected(self):
        p=packet(self.run); record(self.files,p); record(self.files,p)
        self.assertEqual(self.files.load()["runs"][0]["counts"]["post_reads"],1)
        p["items"][0]["summary"]="different"
        with self.assertRaises(ValueError): record(self.files,p)
    def test_new_lineage_is_retained_without_duplicate_item(self):
        p=packet(self.run); record(self.files,p)
        p["id"]="two"; p["items"][0]["url"]=p["items"][0]["url"].replace("/explore/","/search_result/")
        p["items"][0]["discovery_path"]=[{"label":"另一个同行","reason":"新的发现来源"}]
        record(self.files,p)
        state=self.files.load()
        self.assertEqual(len(state["items"]),1)
        self.assertEqual(len(state["items"][0]["discovery_path"]),2)
        self.assertEqual(sum(f.get('origin')!='seed' for f in state["followups"]),1)
    def test_human_review_and_identity_survive_next_run(self):
        p=packet(self.run); record(self.files,p)
        old=self.files.load()["items"][0]
        set_review(self.files,old["id"],"skipped","本周不做")
        finish(self.files,self.run["id"],"synthetic complete","interrupted","user_stopped")
        newer=start_run(self.files,"下一轮合成测试")
        p=packet(newer,"new-round"); p["items"][0]["id"]="cannot-overwrite"
        record(self.files,p)
        updated=self.files.load()["items"][0]
        self.assertEqual(updated["id"],old["id"])
        self.assertEqual(updated["review"]["note"],"本周不做")
        self.assertEqual(len(updated["run_ids"]),2)
    def test_peer_baseline_reused_and_new_posts_counted_once(self):
        source={"name":"合成同行","url":"https://www.xiaohongshu.com/user/profile/bbbbbbbbbbbbbbbbbbbbbbbb",
                "role":"peer","reason":"测试用","checked_at":now(),"seen_posts":[item()["url"]]}
        p={"id":"s1","run_id":self.run["id"],"sources":[source],"counts":{"source_checks":1}}
        record(self.files,p)
        finish(self.files,self.run["id"],"done","interrupted","user_stopped")
        new=start_run(self.files,"再次观察")
        p["id"]="s2";p["run_id"]=new["id"];record(self.files,p)
        self.assertEqual(self.files.load()["runs"][-1]["new_peer_posts"],0)
        self.assertEqual(len(self.files.load()["sources"][0]["seen_posts"]),1)
    def test_unknowns_do_not_become_verified(self):
        obj=item();self.assertIn("费用未核实",unknowns(obj))
        self.assertEqual(evidence_state(obj),"已读原帖")
        obj["historical"]=True
        self.assertEqual(evidence_state(obj),"历史参展线索")
    def test_bad_evidence_rolls_back_entire_packet(self):
        p=packet(self.run)
        p["items"][0]["facts"]={"fees":{"value":"免费","status":"confirmed","source_id":"missing","evidence":"免费"}}
        with self.assertRaises(ValueError): record(self.files,p)
        self.assertEqual(self.files.load()["items"],[])
        self.assertEqual(self.files.load()["runs"][0]["counts"]["post_reads"],0)
    def test_date_only_cannot_be_confirmed(self):
        p=packet(self.run)
        p["items"][0]["official_sources"]=[{"id":"doc","url":"https://official.example.test","read_at":now(),
                                          "authority_basis":"测试夹具","excerpt":"Nov 30"}]
        p["items"][0]["facts"]={"deadline":{"value":"Nov 30","status":"confirmed","source_id":"doc","evidence":"Nov 30"}}
        with self.assertRaises(ValueError):record(self.files,p)
    def test_limits_and_requests_are_honest(self):
        req=request_run(self.files,{"mode":"continue"})
        self.assertEqual(req["status"],"waiting_codex")
        with self.assertRaises(ValueError):start_run(self.files,request_id=req["id"])
        amount=self.run['limits']['searches']+1
        p=packet(self.run);p["counts"]={"searches":amount}
        p["queries"]=[{"query":str(n),"channel":"xhs","reason":"测试"} for n in range(amount)]
        with self.assertRaisesRegex(ValueError,'最多搜索'):record(self.files,p)
        self.assertEqual(self.files.load()["runs"][0]["counts"]['searches'],0)
    def test_concurrent_writes_preserve_both_notes(self):
        record(self.files,packet(self.run))
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(lambda n:request_run(Files(self.files.path),{"mode":"continue"}),range(3)))
        self.assertEqual(len(self.files.load()["requests"]),3)
    def test_csv_formula_text_is_escaped(self):
        p=packet(self.run);p["items"][0]["title"]="=danger()"
        record(self.files,p)
        self.assertIn("'=danger()", (Path(self.tmp.name)/"机会清单.csv").read_text(encoding="utf-8-sig"))
    def test_local_api_saves_and_rejects_unauthorized_writes(self):
        server=make_server(self.files,0)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base+"/api/state") as response: state=json.load(response)
            payload=json.dumps({"mode":"continue"}).encode()
            with self.assertRaises(HTTPError):urlopen(Request(base+"/api/requests",data=payload,headers={"Content-Type":"application/json"}))
            with urlopen(Request(base+"/api/requests",data=payload,headers={"Content-Type":"application/json","X-Demo-Token":state["csrf"]})) as response:
                self.assertEqual(json.load(response)["status"],"waiting_codex")
            with self.assertRaises(HTTPError):urlopen(base+"/../demo.py")
            with urlopen(base+"/api/export.csv") as response:self.assertEqual(response.status,200)
        finally:
            server.shutdown();server.server_close();worker.join()


if __name__=="__main__": unittest.main()
