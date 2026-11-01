"""Getter-only registry observation. No Qt or Designer is imported."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin'))
from substance_physics_scatter.ui_observation import observe,KEY

class Object:
    def __init__(self,parent=None):self.p=parent;self.alive=True
    def objectName(self):return 'TEST_ONLY'
    def parent(self):return self.p
class Widget(Object):
    def layout(self):return None
class Process(Object):
    def state(self):return type('State',(),dict(value=0))()
    def processId(self):return 0
class Layout(Object):
    def count(self):return 0
class App(Object):
    def property(self,key):assert key==KEY;return self.anchor

class Observation(unittest.TestCase):
    def call(self,app,**extra):return observe(app,valid=lambda o:o.alive,pointer=lambda o:(id(o),),qobject=Object,qwidget=Widget,qprocess=Process,on_ui_thread=True,**extra)
    def test_existing_idle_registry_is_observed_without_creation_or_mutation(self):
        app=App();anchor=Object(app);app.anchor=anchor;panel=Widget();panel.process=Process();panel._token=None;panel._phase='idle';panel._closing=False;state=dict(version=1,generation=3,phase='hidden',dock=Widget(),panel=panel,layout=Layout(),shutdown_process=None);anchor.scatter_state=state;before=dict(state)
        result=self.call(app);self.assertEqual(state,before);self.assertEqual(result['status'],'observed');self.assertEqual(result['registry']['generation'],3);self.assertEqual(result['process']['state'],0);self.assertEqual(result['mutations'],0);self.assertEqual(result['layout']['count'],0);self.assertIs(result['panel']['operation_pending'],False)
    def test_missing_or_invalid_anchor_never_constructs_a_registry(self):
        app=App();app.anchor=None;self.assertEqual(self.call(app)['status'],'unavailable');self.assertIsNone(app.anchor)
        app.anchor=Object();app.anchor.alive=False;self.assertEqual(self.call(app)['status'],'unavailable');self.assertFalse(hasattr(app.anchor,'scatter_state'))
    def test_wrong_thread_and_large_layout_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,'UI thread'):observe(App(),valid=lambda _:True,pointer=id,qobject=Object,qwidget=Widget,qprocess=Process,on_ui_thread=False)
        app=App();app.anchor=Object();layout=Layout();layout.count=lambda:17;app.anchor.scatter_state=dict(layout=layout)
        with self.assertRaisesRegex(RuntimeError,'16 items'):self.call(app)

if __name__=='__main__':unittest.main(verbosity=2)
