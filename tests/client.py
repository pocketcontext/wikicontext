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
if __name__=='__main__':unittest.main()
