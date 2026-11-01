from pathlib import Path
import importlib,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter import lifecycle

class Widget:
    def __init__(self):self.valid=True;self.visible=False;self.enabled=True;self.process=None
class Process(Widget):
    def __init__(self):super().__init__();self.callbacks=[];self.done=False
class Host:
    def __init__(self):self.native=[];self.disposed=[];self.layout_count=0;self.deferred=[];self.fail=False
    def valid(self,obj):return obj is not None and obj.valid
    def create_dock(self,identifier):
        self.native.append(identifier)
        if self.fail:raise OSError("native creation failed")
        return Widget()
    def create_panel(self,dock):return Widget()
    def layout(self,dock):self.layout_count+=1;return Widget()
    def attach(self,layout,panel):pass
    def enable(self,panel,enabled):assert panel.valid;panel.enabled=enabled
    def show(self,widget):assert widget.valid;widget.visible=True
    def hide(self,widget):assert widget.valid;widget.visible=False
    def process(self,panel):assert panel.valid;return panel.process
    def on_finished(self,process,callback):assert process.valid;process.callbacks.append(callback)
    def cancel(self,panel):assert panel.valid;self.cancelled=panel
    def clear_process(self,panel):assert panel.valid;panel.process=None
    def finished(self,process):assert process.valid;return process.done
    def defer(self,callback):self.deferred.append(callback)
    def dispose_child(self,layout,panel):assert panel.valid;self.disposed.append(panel);panel.valid=False

class LifecycleTests(unittest.TestCase):
    def setUp(self):self.state={};self.host=Host();self.session=lifecycle.Session(self.state,self.host)
    def test_duplicate_init_hide_show_and_reload_reuse(self):
        panel=self.session.initialize();dock=self.state["dock"]
        self.assertIs(self.session.initialize(),panel)
        self.session.hide();self.assertFalse(dock.visible)
        importlib.reload(lifecycle)
        again=lifecycle.Session(self.state,self.host)
        self.assertIs(again.initialize(),panel);self.assertTrue(dock.visible)
        self.assertEqual(len(self.host.native),1);self.assertEqual(self.host.layout_count,1)
        self.assertTrue(self.host.native[0].startswith("substance_physics_scatter_"))
    def test_idle_shutdown_retains_host_root_and_reuses_layout(self):
        first=self.session.initialize();dock=self.state["dock"];layout=self.state["layout"]
        self.session.shutdown();self.assertIn(first,self.host.disposed);self.assertTrue(dock.valid);self.assertFalse(dock.visible)
        second=self.session.initialize();self.assertIsNot(first,second);self.assertIs(self.state["layout"],layout);self.assertEqual(len(self.host.native),1)
    def test_active_shutdown_finishes_asynchronously_and_late_callback_is_ignored(self):
        first=self.session.initialize();process=Process();first.process=process
        self.session.shutdown();self.assertEqual(self.state["phase"],"stopping");self.assertFalse(first.enabled);self.assertEqual(self.host.disposed,[])
        with self.assertRaises(RuntimeError):self.session.initialize()
        callback=process.callbacks[0];process.done=True;callback(9,None)
        self.assertEqual(self.state["phase"],"hidden");second=self.session.initialize();callback(9,None)
        self.assertIs(self.state["panel"],second);self.assertTrue(second.valid);self.assertEqual(len(self.host.disposed),1)
    def test_invalid_wrappers_are_not_called(self):
        first=self.session.initialize();first.valid=False
        replacement=self.session.initialize();self.assertIsNot(first,replacement)
        dead=Process();dead.valid=False;replacement.process=dead
        self.session.shutdown();self.assertIsNone(self.state["panel"])
        self.state["dock"].valid=False
        with self.assertRaises(RuntimeError):self.session.initialize()
        self.assertEqual(len(self.host.native),1)
    def test_native_failure_is_latched(self):
        self.host.fail=True
        with self.assertRaises(OSError):self.session.initialize()
        with self.assertRaises(RuntimeError):self.session.initialize()
        self.assertEqual(len(self.host.native),1)
    def test_already_finished_process_defers_cleanup(self):
        panel=self.session.initialize();process=Process();process.done=True;panel.process=process
        self.session.shutdown();self.assertEqual(self.host.disposed,[])
        self.host.deferred[0]();self.assertIsNone(self.state["panel"])

if __name__=="__main__":unittest.main(verbosity=2)
