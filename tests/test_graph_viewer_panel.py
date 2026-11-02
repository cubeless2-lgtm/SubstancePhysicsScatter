"""Panel Graph/viewer orchestration without Qt, SDK or HTTP."""
import copy,hashlib,json,re,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from test_graph_mask_ui import panel_class,Value


class GraphViewerPanel(unittest.TestCase):
    def setUp(self):
        self.queue=[];self.sent=[];self.messages=[]
        self.designer=types.SimpleNamespace(resolve_scatter=lambda _:object(),require_metadata_unchanged=lambda *_:None,checked_current=lambda *_:None,inspect_terminal_selection=lambda *a:{'selected_context':{'same':True}})
        cls=panel_class(self.designer,self.queue);cls._viewer_graph_uploaded.__globals__['re']=re
        self.p=cls.__new__(cls);self.p._valid=lambda _:True;self.p._capture_directory=lambda _:'.';self.p.message=self.messages.append
        self.p._viewer_graph_post=lambda token,path,payload,callback,**kw:self.sent.append((path,json.loads(payload)))
        self.token={'target':{},'metadata':{},'jobs':object(),'viewer_graph':{'png_sha':'a'*64,'claim_sha':'b'*64,'selection':{},'context':{'same':True},'forbidden':[],
             'draft':{'revision':'d'*32,'current_job_id':'e'*32,'settings':{'assets':[{'asset_id':'f'*32}],'simulation':{'count':4},'bake':{'resolution':64},'mask_id':None}}}}
    def test_submitted_settings_and_verified_mask_bound_to_revision(self):
        self.p._viewer_graph_uploaded(self.token,json.dumps({'mask_id':'c'*32,'sha256':'a'*64,'provenance_sha256':'b'*64}).encode())
        path,body=self.sent[0];self.assertEqual(path,'api/run')
        self.assertEqual(body['mask_id'],'c'*32);self.assertEqual(body['graph_mask_provenance_sha256'],'b'*64)
        self.assertEqual(body['designer_draft_revision'],'d'*32);self.assertEqual(body['expected_current_job_id'],'e'*32)
        self.assertEqual(body['assets'],[{'asset_id':'f'*32}]);self.assertTrue(self.token['viewer_graph']['submit_pending'])
    def test_changed_graph_or_wrong_upload_never_submits(self):
        for bad in ({'mask_id':'c'*32,'sha256':'0'*64,'provenance_sha256':'b'*64},{'mask_id':'c'*32,'sha256':'a'*64,'provenance_sha256':'0'*64}):
            with self.assertRaises(ValueError):self.p._viewer_graph_uploaded(self.token,json.dumps(bad).encode())
        self.designer.inspect_terminal_selection=lambda *a:{'selected_context':{'changed':True}}
        with self.assertRaises(ValueError):self.p._viewer_graph_uploaded(self.token,json.dumps({'mask_id':'c'*32,'sha256':'a'*64,'provenance_sha256':'b'*64}).encode())
        self.assertEqual(self.sent,[])
    def test_cancel_during_submission_waits_for_owned_token(self):
        value=self.token['viewer_graph'];value.update(submit_pending=True,cancel_requested=False)
        self.p._token=self.token;self.p.process=None;self.p._cancel_owned=lambda _:None
        self.p.stop();self.assertTrue(value['cancel_requested']);self.assertTrue(value['submit_pending'])
        cancelled=[];self.p._viewer_graph_cancel=lambda token:cancelled.append(token)
        self.p._viewer_graph_started(self.token,json.dumps({'token':'1'*32}).encode())
        self.assertEqual(cancelled,[self.token]);self.assertEqual(value['run_token'],'1'*32)
    def test_poll_failure_attempts_only_owned_cancel(self):
        value=self.token['viewer_graph'];value.update(run_token='2'*32,cancel_requested=False)
        cancelled=[];self.p._viewer_graph_cancel=lambda token:cancelled.append(token['viewer_graph']['run_token'])
        self.p._handoff_failure(self.token,'poll failed')
        self.assertEqual(cancelled,['2'*32]);self.assertTrue(value['cancel_requested'])
    def test_viewer_session_uses_server_64_hex_csrf_token(self):
        requested=[];self.p._handoff_get=lambda token,path,limit,callback:requested.append(path)
        self.p._viewer_graph_state(self.token,json.dumps({'session_token':'a'*64}).encode())
        self.assertEqual(requested,['api/designer-draft'])
        with self.assertRaises(ValueError):self.p._viewer_graph_state(self.token,json.dumps({'session_token':'a'*32}).encode())
    def test_capture_claim_uses_server_canonical_bytes(self):
        self.p._viewer_graph_capture.__globals__['hashlib']=hashlib
        raw=b'owned-png-bytes';saved=[]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mask.png';path.write_bytes(raw)
            self.token['id']='3'*32
            self.designer.capture_terminal=lambda *a:{'png':{'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'capture':{'source':'한글'},'operation_authored_payload':{'z':1,'a':2}}
            self.p._viewer_graph_upload=lambda token,png,claim:saved.append((png,claim))
            with patch('substance_physics_scatter.core._validated_capture',lambda _:None):self.p._viewer_graph_capture(self.token)
        png,claim=saved[0];self.assertEqual(png,raw)
        self.assertEqual(claim,json.dumps(json.loads(claim),sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8'))
        self.assertEqual(self.token['viewer_graph']['claim_sha'],hashlib.sha256(claim).hexdigest())
    def test_handoff_stages_before_final_manifest_request(self):
        order=[];self.p._stage_handoff=lambda token:order.append('stage') or {'height':'owned'}
        self.p._handoff_get=lambda token,path,limit,callback:order.append(('manifest',path))
        self.token['viewer_handoff']={'index':3,'roles':['height','normal','coverage'],'job':'a'*32}
        self.p._handoff_next(self.token)
        self.assertEqual(order,['stage',('manifest','api/designer-handoff/'+'a'*32)])
        self.assertEqual(self.token['viewer_handoff']['files'],{'height':'owned'})

if __name__=='__main__':unittest.main()
