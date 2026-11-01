"""Pure tests of the actual transfer methods, without creating Qt/Designer objects."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

source=Path(__file__).resolve().parents[1]/'plugin/substance_physics_scatter/windowing.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
methods=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Presentation')
keep={'move','show','hide','_redirect_native_show','detach'}
namespace={'idle':lambda p:p.idle,'floating_rect':lambda x:x}
for method in methods.body:
    if isinstance(method,ast.FunctionDef) and method.name in keep:
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
Controller=type('Controller',(),{key:namespace[key] for key in keep})
class Widget:
    def __init__(self):self.visible=False;self.panel=None
    def show(self):self.visible=True
    def hide(self):self.visible=False
    def raise_(self):pass
    def screen(self):return None
    def widget(self):return self.panel
    def takeWidget(self):p=self.panel;self.panel=None;return p
class Layout:
    def __init__(self,*items):self.items=list(items)
    def indexOf(self,w):return self.items.index(w) if w in self.items else -1
    def addWidget(self,w):self.items.append(w)
    def removeWidget(self,w):
        if w in self.items:self.items.remove(w)

def setup():
    c=Controller();c.state={'phase':'ready'};c.panel=SimpleNamespace(idle=True,message=lambda text:None)
    c.native=Widget();c.body=Widget();c.window=Widget();c.toolbar=Widget();c.scroll=Widget();c.scroll.panel=c.panel
    c.layout=Layout(c.toolbar,c.scroll);c.window_layout=Layout();c.separate=False;c.transition=False
    c.move_failed=False;c.float_initialized=False;c.redirect_pending=False
    return c
class TransferTests(unittest.TestCase):
    def test_roundtrip_same_panel_and_children(self):
        c=setup();p=c.panel;c.move(True)
        self.assertTrue(c.window.visible);self.assertFalse(c.native.visible)
        self.assertEqual(c.window_layout.items,[c.toolbar,c.scroll]);self.assertIs(c.scroll.widget(),p)
        c.move(False);self.assertTrue(c.native.visible);self.assertFalse(c.window.visible)
        self.assertEqual(c.layout.items,[c.toolbar,c.scroll]);self.assertIs(c.panel,p)
    def test_busy_denied(self):
        c=setup();c.panel.idle=False;c.move(True)
        self.assertFalse(c.separate);self.assertEqual(len(c.layout.items),2)
    def test_hide_menu_reopen_and_shutdown_detach(self):
        c=setup();p=c.panel;c.move(True);c.hide()
        self.assertFalse(c.window.visible);self.assertIs(c.panel,p)
        c._redirect_native_show();self.assertTrue(c.window.visible)
        c.state['phase']='stopping';c.hide();c._redirect_native_show();self.assertFalse(c.window.visible)
        c.detach(p);self.assertIsNone(c.scroll.widget());self.assertIsNone(c.panel)
    def test_ambiguous_layout_latches(self):
        c=setup();c.layout.items=[]
        with self.assertRaises(RuntimeError):c.move(True)
        self.assertTrue(c.move_failed)
        with self.assertRaises(RuntimeError):c.move(True)
if __name__=='__main__':unittest.main()
