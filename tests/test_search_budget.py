"""Only searches consume a budget; reads, source checks and duration have no quotas."""
import copy
from pathlib import Path
import tempfile
import unittest
from demo import Files,finish,now,record,request_run,start_run
from workflow import migrate


class SearchBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.files=Files(Path(self.tmp.name)/'workspace.json')
    def tearDown(self):self.tmp.cleanup()
    def begin(self,limit=2):
        request=request_run(self.files,{'mode':'new','platforms':['web'],'max_searches':limit})
        return start_run(self.files,request_id=request['id'])
    def searches(self,run,amount,key='queries'):
        return {'id':key,'run_id':run['id'],'counts':{'searches':amount},'queries':[
            {'query':'相同关键词仍消耗搜索次数','channel':'web','reason':'隔离测试，非真实搜索'} for _ in range(amount)]}
    def test_exact_budget_rejects_extra_search_without_discarding_later_reads(self):
        run=self.begin();saved=record(self.files,self.searches(run,2))
        self.assertEqual(saved['searches_remaining'],0);self.assertTrue(saved['search_budget_reached'])
        before=self.files.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'最多搜索2次'):record(self.files,self.searches(run,1,'over-budget'))
        self.assertEqual(self.files.path.read_bytes(),before)
        saved=record(self.files,{'id':'unbounded-reads','run_id':run['id'],
            'counts':{'post_reads':100,'source_checks':30,'official_reads':80},
            'read_post_urls':['https://example.test/read/'+str(n) for n in range(100)],
            'sources':[{'name':'合成机构'+str(n),'url':'https://example.test/source/'+str(n),
                'role':'organizer','reason':'隔离计数测试','checked_at':now()} for n in range(30)]})
        self.assertEqual(saved['counts'],{'searches':2,'post_reads':100,'source_checks':30,'official_reads':80})
        ended=finish(self.files,run['id'],'隔离测试：预算后继续保存核验','completed','budget_reached')
        self.assertEqual(ended['limits'],{'searches':2});self.assertNotIn('max_minutes',ended)
    def test_ending_early_has_no_minimum_counts_or_duration(self):
        run=self.begin()
        ended=finish(self.files,run['id'],'隔离测试：没有值得继续的线索','partial','low_yield')
        self.assertEqual(ended['counts']['searches'],0);self.assertEqual(ended['targets'],{})
    def test_search_budget_reason_cannot_be_used_for_other_counters(self):
        run=self.begin()
        record(self.files,{'id':'many-official-reads','run_id':run['id'],'counts':{'official_reads':200}})
        with self.assertRaisesRegex(ValueError,'最大搜索次数'):finish(self.files,run['id'],'不是搜索预算','partial','budget_reached')
        with self.assertRaisesRegex(ValueError,'不设时间'):finish(self.files,run['id'],'无时间限制','partial','time_budget')
    def test_per_request_limit_is_saved_even_if_project_settings_change(self):
        first=request_run(self.files,{'mode':'new','platforms':['web'],'max_searches':'2'})
        second=request_run(self.files,{'mode':'continue','project_id':first['project_id'],'max_searches':'7'})
        run=start_run(self.files,request_id=first['id']);self.assertEqual(run['limits'],{'searches':2})
        finish(self.files,run['id'],'隔离测试结束','interrupted','user_stopped')
        self.assertEqual(start_run(self.files,request_id=second['id'])['limits'],{'searches':7})
    def test_invalid_search_limits_never_create_requests(self):
        for value in [0,-1,True,2.5,'2.5','',None]:
            with self.assertRaises(ValueError):request_run(self.files,{'mode':'new','max_searches':value})
        self.assertFalse(self.files.path.exists())
    def test_legacy_limits_are_removed_but_search_cap_and_history_are_preserved(self):
        run=self.begin(16);data=self.files.load();row=data['runs'][0]
        row.update(max_minutes=45,targets={'searches':6,'post_reads':15,'source_checks':3,'platforms':3})
        row['limits'].update(post_reads=40,source_checks=10,official_reads=20)
        row['counts'].update(post_reads=100,source_checks=30,official_reads=80)
        restored=migrate(copy.deepcopy(data))['runs'][0]
        self.assertEqual(restored['id'],run['id']);self.assertEqual(restored['limits'],{'searches':16})
        self.assertEqual(restored['counts']['post_reads'],100);self.assertEqual(restored['targets'],{})
        self.assertNotIn('max_minutes',restored)


if __name__=='__main__':unittest.main()
