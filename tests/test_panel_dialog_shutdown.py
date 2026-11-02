"""Panel shutdown waits for settings snapshot/upload and worker completion."""
import types,unittest
from test_graph_mask_ui import panel_class

class Dialog:
    def __init__(self,fail=False):self.callback=None;self.calls=0;self.fail=fail
    def request_shutdown(self,callback):
        self.calls+=1
        if self.fail:raise RuntimeError('cannot confirm')
        self.callback=callback

class PanelDialogShutdown(unittest.TestCase):
    def setUp(self):
        cls=panel_class(types.SimpleNamespace(),[]);self.p=cls.__new__(cls)
        p=self.p;p._token=None;p.process=None;p._closing=False;p._shutdown_acks=[];p._viewer_settings_dialog=Dialog();p.stop=lambda:None;p.messages=[];p.message=p.messages.append
    def test_waits_for_dialog_and_dispatches_each_ack_once(self):
        got=[];self.p.request_shutdown(lambda:got.append(1));self.p.request_shutdown(lambda:got.append(2))
        self.assertEqual(got,[]);self.assertEqual(self.p._viewer_settings_dialog.calls,1)
        self.p._viewer_settings_dialog.callback();self.p._viewer_settings_dialog.callback()
        self.assertEqual(got,[1,2])
    def test_waits_for_both_dialog_and_worker(self):
        got=[];self.p._token={'owned':True};self.p.process=object()
        self.p.request_shutdown(lambda:got.append('done'));self.p._viewer_settings_dialog.callback()
        self.assertEqual(got,[]);self.p._token=None;self.p.process=None;self.p._try_shutdown_acks()
        self.assertEqual(got,['done'])
    def test_unknown_dialog_shutdown_never_acknowledges(self):
        got=[];self.p._viewer_settings_dialog=Dialog(fail=True)
        self.p.request_shutdown(lambda:got.append('done'));self.p._try_shutdown_acks()
        self.assertEqual(got,[]);self.assertIn('could not be confirmed',self.p.messages[-1])

if __name__=='__main__':unittest.main()
