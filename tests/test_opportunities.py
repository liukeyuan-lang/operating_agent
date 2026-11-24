"""Opportunity groups and multiple source links; synthetic data only."""
import copy
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path

from demo import Files,now,public_state,record,request_run,start_run
from leads import remove_lead
from opportunities import related_links
from test_demo import item
from workflow import GATES,REQUIRED,profile_digest,project


class OpportunityTest(unittest.TestCase):
    def test_links_from_all_saved_origins_are_merged_without_claiming_official_status(self):
        obj=item()
        obj['official_sources']=[{'url':'https://example.test/call','title':'合成官方公告','authority_basis':'合成来源链'}]
        obj['facts']={'entry_url':{'value':'https://example.test/apply','status':'confirmed'}}
        obj['author_url']='https://www.xiaohongshu.com/user/profile/bbbbbbbbbbbbbbbbbbbbbbbb'
        obj['discovery_path']=[{'url':'https://example.test/news?utm_source=one','label':'聚合转载','reason':'从转载找到主办方'}]
        obj['verification_attempt']={'urls':['https://example.test/news','https://example.test/blocked']}
        obj['related_links']=[{'url':'https://example.test/faq','title':'补充说明'}]
        rows=related_links(obj)
        self.assertEqual(len(rows),7)
        news=next(r for r in rows if '/news' in r['url'])
        self.assertEqual(news['kinds'],['发现路径','核验入口'])
        self.assertNotIn('官方来源',news['kinds'])
        self.assertEqual(next(r for r in rows if r['url'].endswith('/apply'))['kinds'],['报名入口'])
        self.assertEqual(next(r for r in rows if r['url'].endswith('/blocked'))['kinds'],['核验入口'])
    def test_unsafe_links_are_omitted_and_signed_visit_url_is_retained(self):
        obj=item();obj['url']+='?xsec_token=sample-token&xsec_source=pc_search'
        obj['discovery_path']=[{'url':item()['url'],'label':'同一原帖'}]
        obj['related_links']=[{'url':u} for u in ['javascript:alert(1)','file:///secret','https://user:password@example.test/','not-a-url']]
        rows=related_links(obj)
        self.assertEqual(len(rows),1)
        self.assertIn('xsec_token=sample-token',rows[0]['url'])
        self.assertEqual(rows[0]['kinds'],['发现来源','发现路径'])
    def test_legacy_entry_fact_with_comment_uses_actual_url_and_merges_official_form(self):
        obj=item();obj['official_sources']=[{'url':'https://example.test/form','title':'官方表单'}]
        obj['facts']={'entry_url':{'value':'https://example.test/form（报名问卷；仅记录）','status':'confirmed'}}
        obj['discovery_path']=[{'kind':'search','label':'初始搜索','url':'https://example.test/search'}]
        rows=related_links(obj)
        self.assertEqual(len(rows),2)
        form=next(r for r in rows if r['url'].endswith('/form'))
        self.assertEqual(form['kinds'],['官方来源','报名入口'])
    def test_pending_verified_and_known_closed_are_separate_and_project_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            files=Files(Path(folder)/'state.json');run=start_run(files);p=project(files.load())
            verified=item();verified['title']='合成已验证'
            verified['official_sources']=[{'id':'official','url':'https://example.test/call','title':'合成公告','read_at':now(),
                'authority_basis':'合成夹具','excerpt':'fixture evidence'}]
            verified['facts']={k:{'value':'fixture','status':'confirmed','source_id':'official','evidence':'fixture evidence'} for k in REQUIRED}
            verified['facts']['deadline']['at']=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
            verified['facts']['open_status']['value']='open';verified['facts']['ai_policy']['allowed']=True
            verified['participation']={'profile_digest':profile_digest(p),'checked_at':now(),**{g:{'status':'pass','reason':'合成条件通过'} for g in GATES}}
            pending=item();pending.update(title='合成待验证',url='https://www.xiaohongshu.com/explore/bbbbbbbbbbbbbbbbbbbbbbbb')
            closed=copy.deepcopy(pending);closed.update(title='合成已关闭',url='https://www.xiaohongshu.com/explore/cccccccccccccccccccccccc',excluded_reason='已截止')
            record(files,{'id':'fixture','run_id':run['id'],'items':[verified,pending,closed]})
            view=public_state(files)
            self.assertEqual([i['title'] for i in view['results']],['合成已验证'])
            self.assertEqual([i['title'] for i in view['pending_opportunities']],['合成待验证'])
            self.assertEqual(view['stats']['opportunities'],2)
            for obj in view['results']+view['pending_opportunities']:self.assertTrue(obj['related_links'])
            pending_id=view['pending_opportunities'][0]['id']
            remove_lead(files,{'id':'items:'+pending_id},now())
            self.assertEqual(public_state(files)['pending_opportunities'],[])
            request_run(files,{'mode':'new','name':'独立项目','direction':'合成方向','assets_brief':'未知'})
            self.assertEqual(public_state(files)['stats']['opportunities'],0)


if __name__=='__main__':unittest.main()
