"""Pure presentation lifecycle checks; no Qt/SDK imports."""
import unittest
from test_lifecycle import Host,Widget,lifecycle

class Presentation:
    def __init__(self):self.panel=None;self.shown=0;self.hidden=0;self.detached=[]
    def attach(self,panel):self.panel=panel
    def show(self):self.shown+=1
    def hide(self):self.hidden+=1
    def detach(self,panel):
        assert self.panel is panel
        self.detached.append(panel);self.panel=None

class PresentedHost(Host):
    def __init__(self):super().__init__();self.enables=[]
    def presentation(self,state,panel):
        if 'presentation' not in state:state['presentation']=Presentation()
        state['presentation'].attach(panel)
    def enable(self,panel,enabled):self.enables.append(enabled);super().enable(panel,enabled)

class WindowLifecycleTests(unittest.TestCase):
    def test_busy_hidden_reopen_preserves_panel_and_does_not_enable(self):
        state={};host=PresentedHost();session=lifecycle.Session(state,host)
        panel=session.initialize();panel.process=Widget();panel.enabled=False
        count=len(host.enables);generation=state['generation']
        session.hide();self.assertIs(session.initialize(),panel)
        self.assertEqual(len(host.enables),count);self.assertFalse(panel.enabled)
        self.assertEqual(state['generation'],generation);self.assertEqual(len(host.native),1)
    def test_shutdown_detaches_child_and_reuses_controller_root(self):
        state={};host=PresentedHost();session=lifecycle.Session(state,host)
        first=session.initialize();presentation=state['presentation'];dock=state['dock']
        session.shutdown();self.assertEqual(presentation.detached,[first])
        second=session.initialize();self.assertIs(state['presentation'],presentation)
        self.assertIs(state['dock'],dock);self.assertIs(presentation.panel,second)
        self.assertEqual(len(host.native),1)

if __name__=='__main__':unittest.main()
