import os
import sqlite3
import unittest
from unittest.mock import patch
from access_control import TestAccess
from status_report import render_access,render_status


class StatusTests(unittest.TestCase):
    def test_global_off_owner_and_named_grants_report(self):
        c=sqlite3.connect(':memory:');a=TestAccess(c,'1414798445')
        try:
            a.change('1414798445','old','123','alice','fact',True)
            a.invokes.apply('1414798445','new',['456'],'set',3,'stream')
            a.invokes.reserve('456','use','stream')
            with patch.dict(os.environ,{'ROBORATH_OWNER_ONLY_TEST_MODE':'true','ROBORATH_QA_GRANTED_TESTERS':'true'}):
                report=render_access(a,'stream')
                self.assertIn('@alice',report)
                self.assertIn('2 left',report)
                self.assertLessEqual(len(report.encode()),360)
                a.invokes.apply('1414798445','off',[],'global_off',None,'stream')
                self.assertIn('GLOBAL OFF',render_status(a,'stream',True,'Hermes'))
                self.assertTrue(a.can_receive('1414798445','!ask hello',True))
                self.assertFalse(a.can_receive('123','!ask hello',True))
        finally:c.close()
