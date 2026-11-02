"""Slot rebinding must preserve unrelated listeners and roll back a failed refresh."""
import sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import panel_upgrade as upgrade

class Signal:
    def __init__(self,fail=False):self.listeners=[];self.fail=fail
    def connect(self,slot):
        if self.fail:self.fail=False;raise RuntimeError('injected failure')
        self.listeners.append(slot)
    def disconnect(self,slot):self.listeners.remove(slot);return True

class Refresh(unittest.TestCase):
    def panel(self):
        names=tuple(dict.fromkeys(upgrade.METHODS+upgrade.GRAPH_METHODS))
        def old(self,*args):return 'old'
        def new(self,*args):return 'new'
        p=types.SimpleNamespace(_viewer_ui_upgrade=True,_viewer_graph_upgrade=True,_phase='idle',_token=None,process=None,_closing=False,_lifecycle_stopping=False)
        old_class=type('Old',(),{name:old for name in names});new_class=type('New',(),{name:new for name in names})
        for name in names:setattr(p,name,types.MethodType(getattr(old_class,name),p))
        for widget,method in (('viewer_open','open_local_viewer'),('viewer_check','check_local_viewer'),('viewer_apply','apply_viewer_result'),('viewer_graph_run','run_viewer_graph'),('viewer_graph_cancel','stop')):
            sig=Signal();sig.connect(getattr(p,method));sig.connect(self.extra);setattr(p,widget,types.SimpleNamespace(clicked=sig))
        return p,new_class,names
    def extra(self,*args):pass
    def test_refresh_keeps_extra_listeners_and_changes_slots(self):
        p,cls,names=self.panel();self.assertTrue(upgrade.refresh_methods(p,cls))
        for name in names:self.assertIs(getattr(p,name).__func__,getattr(cls,name))
        for widget in ('viewer_open','viewer_check','viewer_apply','viewer_graph_run','viewer_graph_cancel'):
            self.assertIn(self.extra,getattr(p,widget).clicked.listeners);self.assertEqual(len(getattr(p,widget).clicked.listeners),2)
    def test_partial_connection_failure_restores_old_slots(self):
        p,cls,names=self.panel();original={name:getattr(p,name) for name in names};p.viewer_apply.clicked.fail=True
        with self.assertRaisesRegex(RuntimeError,'injected'):upgrade.refresh_methods(p,cls)
        for name in names:self.assertEqual(getattr(p,name),original[name])
        for widget,method in (('viewer_open','open_local_viewer'),('viewer_check','check_local_viewer'),('viewer_apply','apply_viewer_result'),('viewer_graph_run','run_viewer_graph'),('viewer_graph_cancel','stop')):
            self.assertIn(original[method],getattr(p,widget).clicked.listeners);self.assertIn(self.extra,getattr(p,widget).clicked.listeners)
    def test_busy_panel_is_not_touched(self):
        p,cls,names=self.panel();p._phase='running';old=p.run
        with self.assertRaisesRegex(ValueError,'Wait'):upgrade.refresh_methods(p,cls)
        self.assertEqual(p.run,old)

if __name__=='__main__':unittest.main()
