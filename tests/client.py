#!/usr/bin/env python3
"""Read throttling retries are bounded; uncertain writes are never replayed."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('wc',Path(__file__).resolve().parents[1]/'skills/wikicontext/scripts/wc.py')
wc=importlib.util.module_from_spec(spec);spec.loader.exec_module(wc)
class Client(unittest.TestCase):
    def test_throttled_read(self):
        with patch.object(wc,'call',side_effect=[(429,{}),(200,{'rows':[]})]) as call,patch.object(wc.time,'sleep') as sleep:
            self.assertEqual(wc.must({},'POST','/api/context/query',{}),{'rows':[]})
            self.assertEqual(call.call_count,2);sleep.assert_called_once_with(10)
    def test_no_write_replay(self):
        with patch.object(wc,'call',return_value=(503,{})) as call,patch.object(wc.time,'sleep') as sleep:
            with self.assertRaises(wc.Fail):wc.must({},'POST','/api/collections/pages/records',{})
            self.assertEqual(call.call_count,1);sleep.assert_not_called()
    def test_retry_budget(self):
        with patch.object(wc,'call',return_value=(503,{})) as call,patch.object(wc.time,'sleep'):
            with self.assertRaises(wc.Fail):wc.must({},'POST','/api/context/query',{})
            self.assertEqual(call.call_count,4)
    def test_publish_preserves_staged_fields(self):
        args=wc.parse(['publish','a'*15,'--expected-revision','2'])
        with patch.object(wc,'config',return_value={}),patch.object(wc,'must',return_value={}) as request,patch.object(wc,'say'):
            wc.run(args)
        request.assert_called_once_with({},'PATCH',wc.records('ingestion_runs','a'*15),{'expected_revision':2,'status':'published'})
    def test_publish_home_requires_explicit_base(self):
        args=wc.parse(['publish','a'*15,'--expected-revision','2','--home','onboarding'])
        with patch.object(wc,'must') as request:
            with self.assertRaises(wc.Fail):wc.home_fields({},args)
        request.assert_not_called()
    def test_staging_does_not_refresh_existing_choice(self):
        args=wc.parse(['stage-home','a'*15,'--expected-revision','2','--clear-home'])
        with patch.object(wc,'must',return_value={'columns':['home','clear_home'],'rows':[['b'*15,False]]}) as request:
            with self.assertRaises(wc.Fail):wc.home_fields({},args)
        self.assertEqual(request.call_count,1)
    def test_home_conflict_is_not_replayed(self):
        args=wc.parse(['publish','a'*15,'--expected-revision','2'])
        with patch.object(wc,'config',return_value={}),patch.object(wc,'call',return_value=(409,{})) as request:
            with self.assertRaises(wc.Fail) as error:wc.run(args)
        self.assertEqual(error.exception.code,4)
        self.assertEqual(request.call_count,1)
if __name__=='__main__':unittest.main()
