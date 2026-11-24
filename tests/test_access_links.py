"""Persist real visit URLs while retaining canonical, project-scoped identities."""
import copy
import tempfile
import unittest
from pathlib import Path

from access_links import access_key,resolve_url,signed_url,save_links,url_map
from demo import Files,csv_text,now,public_state,record,request_run,start_run
from research import record_snapshot
from test_demo import item,packet

BARE='https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa'
FULL=BARE+'?xsec_token=fixture-first%3D&xsec_source=pc_search&source=unknown'
NEXT=BARE+'?xsec_token=fixture-next%3D&xsec_source=pc_search'


class AccessLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.files=Files(Path(self.tmp.name)/'state.json')
    def tearDown(self):self.tmp.cleanup()
    def test_record_reload_and_csv_keep_signed_url_but_identity_and_dedup_ignore_token(self):
        run=start_run(self.files);p=packet(run);p['items'][0]['url']=FULL;record(self.files,p)
        obj=self.files.load()['items'][0];ident=obj['id']
        self.assertEqual(obj['url'],BARE)
        self.assertEqual(url_map(self.files.load(),obj['project_id'])[BARE],FULL)
        p['id']='second';p['items'][0]['url']=NEXT;record(self.files,p)
        view=public_state(self.files)
        self.assertEqual(len(view['items']),1);self.assertEqual(view['items'][0]['id'],ident)
        self.assertEqual(view['items'][0]['access_url'],NEXT)
        self.assertIn(NEXT,[r['url'] for r in view['pending_opportunities'][0]['related_links']])
        self.assertIn('fixture-next',csv_text(self.files.load()))
        p['id']='third';p['items'][0]['url']=BARE;record(self.files,p)
        self.assertEqual(public_state(self.files)['items'][0]['access_url'],NEXT)
    def test_saved_late_signature_upgrades_first_bare_link_and_applies_to_evidence_and_sources(self):
        run=start_run(self.files);record(self.files,packet(run))
        save_links(self.files,{'urls':[FULL]},now())
        view=public_state(self.files)
        self.assertEqual(view['items'][0]['related_links'][0]['url'],FULL)
        self.assertEqual(view['items'][0]['related_links'][0]['access_status'],'signed')
        self.assertEqual(view['items'][0]['bucket'],'lead')
    def test_signature_is_not_reused_for_different_note_or_other_project(self):
        save_links(self.files,{'urls':[FULL]},now());pid=self.files.load()['active_project_id']
        other=BARE.replace('a'*24,'b'*24)
        self.assertEqual(resolve_url(other,url_map(self.files.load(),pid)),other)
        request_run(self.files,{'mode':'new','name':'隔离项目','direction':'测试','assets_brief':'未知'})
        self.assertEqual(public_state(self.files)['access_urls'],{})
    def test_redacted_values_and_mismatched_registry_keys_cannot_become_visit_links(self):
        for token in ['<redacted>','%3Credacted%3E','REDACTED','...','']:
            self.assertFalse(signed_url(BARE+'?xsec_token='+token))
        save_links(self.files,{'urls':[FULL]},now())
        data=self.files.load();pid=data['active_project_id'];data['access_links'][0]['key']=BARE.replace('a'*24,'b'*24)
        self.assertEqual(url_map(data,pid),{})
    def test_failed_ingest_rolls_back_full_url_registry_too(self):
        run=start_run(self.files);p=packet(run);p['items'][0]['url']=FULL;p['items'][0]['fit']='invalid'
        with self.assertRaises(ValueError):record(self.files,p)
        self.assertEqual(self.files.load()['access_links'],[])
    def test_snapshots_keep_visit_parameters_even_when_content_id_is_normalized(self):
        record_snapshot(self.files,{'platform':'xiaohongshu','source_type':'platform_browser','query':'测试','sort':'综合','time_window':'未知','scope_note':'合成观察',
             'items':[{'url':FULL,'title':'合成原帖'}]},now())
        s=public_state(self.files)
        self.assertEqual(s['research_snapshots'][0]['items'][0]['url'],BARE)
        self.assertEqual(s['research_snapshots'][0]['items'][0]['access_url'],FULL)


if __name__=='__main__':unittest.main()
