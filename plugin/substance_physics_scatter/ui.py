from __future__ import annotations
import json
import copy
import uuid
import time
import os
import hashlib
import re
import stat
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from .core import Jobs
from .errors import HOST_ERRORS, rollback_or_raise
from . import designer,live_preview

def worker_path():
    root = Path(__file__).resolve().parent
    for path in (root.parents[1] / "build-review-live-ready1/Release/scatter_worker_legacy_live.exe", root.parents[1] / "build-review-motion/Release/scatter_worker_legacy_motion.exe", root / "bin/scatter_worker.exe", root.parents[1] / "build/Release/scatter_worker.exe"):
        if path.is_file():
            return path
    raise FileNotFoundError("scatter_worker.exe is missing; build or reinstall the plugin")

class Panel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.graph = None
        self.jobs = None
        self.process = None
        self.buffer = bytearray()
        self.completed = None
        self.pending_config = None
        self._generation=uuid.uuid4().hex;self._token=None;self._phase='idle';self._closing=False
        self._source_revision=0;self._source_selection=None;self._source_context=None
        self._target_identity=None;self._shutdown_acks=[];self._select_again=False
        self._graph_ui_enabled=True
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("Substance Physics Scatter · 0.3 preview")
        layout.addWidget(title)
        self.viewer_target=QtWidgets.QLabel('Designer target: no scatter selected')
        self.viewer_target.setWordWrap(True);layout.addWidget(self.viewer_target)
        viewer_actions=QtWidgets.QHBoxLayout()
        self.viewer_open=QtWidgets.QPushButton('Open local 3D viewer')
        self.viewer_open.clicked.connect(self.open_local_viewer);viewer_actions.addWidget(self.viewer_open)
        self.viewer_check=QtWidgets.QPushButton('Check viewer connection')
        self.viewer_check.clicked.connect(self.check_local_viewer);viewer_actions.addWidget(self.viewer_check)
        layout.addLayout(viewer_actions)
        self.viewer_apply=QtWidgets.QPushButton('Apply current viewer result to selected Designer graph')
        self.viewer_apply.clicked.connect(self.apply_viewer_result);layout.addWidget(self.viewer_apply)
        self.viewer_settings=QtWidgets.QPushButton('Set viewer simulation in Designer')
        self.viewer_settings.clicked.connect(self.open_viewer_settings);layout.addWidget(self.viewer_settings)
        self.viewer_graph_run=QtWidgets.QPushButton('Capture inspected Graph + run submitted viewer settings')
        self.viewer_graph_run.clicked.connect(self.run_viewer_graph);layout.addWidget(self.viewer_graph_run)
        self.viewer_graph_cancel=QtWidgets.QPushButton('Cancel Graph viewer run')
        self.viewer_graph_cancel.clicked.connect(self.stop);self.viewer_graph_cancel.setEnabled(False);layout.addWidget(self.viewer_graph_cancel)
        self.viewer_draft_status=QtWidgets.QLabel('First submit settings in the 3D viewer. Each new simulation recaptures the Graph; Saved rebake reuses its stored mask.')
        self.viewer_draft_status.setWordWrap(True);layout.addWidget(self.viewer_draft_status)
        self.viewer_status=QtWidgets.QLabel('Local viewer runs separately. Its assets and results are not automatically applied to the selected Designer graph.')
        self.viewer_status.setWordWrap(True);layout.addWidget(self.viewer_status)
        create = QtWidgets.QPushButton("Add independent scatter node")
        create.clicked.connect(self.add)
        layout.addWidget(create)
        self.nodes = QtWidgets.QComboBox()
        self.nodes.currentIndexChanged.connect(self.select)
        layout.addWidget(self.nodes)
        refresh = QtWidgets.QPushButton("Refresh scatter list")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        row = QtWidgets.QHBoxLayout()
        self.mesh = QtWidgets.QLineEdit()
        self.mesh.setPlaceholderText("OBJ mesh (Z-up, meters)")
        browse = QtWidgets.QPushButton("Add OBJ")
        browse.clicked.connect(self.browse)
        row.addWidget(self.mesh); row.addWidget(browse); layout.addLayout(row)
        self.assets = QtWidgets.QTableWidget(0, 3)
        self.assets.setHorizontalHeaderLabels(["OBJ file", "Weight", "Asset scale"])
        self.assets.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.assets.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.assets)
        remove = QtWidgets.QPushButton("Remove selected asset")
        remove.clicked.connect(self.remove_asset); layout.addWidget(remove)
        layout.addWidget(QtWidgets.QLabel("Weights are probabilities; exact object counts are not guaranteed."))
        self._mask_config={"enabled":False};self.mask_enabled=QtWidgets.QCheckBox("Use file mask")
        layout.addWidget(self.mask_enabled)
        mask_row=QtWidgets.QHBoxLayout();self.mask_path=QtWidgets.QLineEdit();self.mask_path.setReadOnly(True);self.mask_path.setPlaceholderText("No mask selected")
        self.mask_browse=QtWidgets.QPushButton("Choose mask PNG");self.mask_browse.clicked.connect(self.browse_mask)
        mask_row.addWidget(self.mask_path);mask_row.addWidget(self.mask_browse);layout.addLayout(mask_row)
        self.mask_snapshot=QtWidgets.QLabel("A mask controls starting centers; physics may move objects outside it.");self.mask_snapshot.setWordWrap(True);layout.addWidget(self.mask_snapshot)
        self.mask_mode=QtWidgets.QComboBox();self.mask_mode.addItems(['File / no mask','Graph terminal']);layout.addWidget(self.mask_mode)
        self.source_choices=QtWidgets.QComboBox();layout.addWidget(self.source_choices)
        self.source_refresh=QtWidgets.QPushButton('List current graph terminals');self.source_refresh.clicked.connect(self.refresh_sources);layout.addWidget(self.source_refresh)
        self.source_inspect=QtWidgets.QPushButton('Inspect selected terminal (compute0, up to3 copies)');self.source_inspect.clicked.connect(self.inspect_source);layout.addWidget(self.source_inspect)
        self.source_status=QtWidgets.QLabel('Graph terminal needs explicit inspection. Capture uses a new compute and up to6 copies.');self.source_status.setWordWrap(True);layout.addWidget(self.source_status)
        self.source_choices.currentIndexChanged.connect(self.invalidate_source)
        form = QtWidgets.QFormLayout()
        self.count = QtWidgets.QSpinBox(); self.count.setRange(1, 5000); self.count.setValue(40)
        self.scale = QtWidgets.QDoubleSpinBox(); self.scale.setRange(.001, 100); self.scale.setDecimals(3); self.scale.setValue(.3)
        self.width = QtWidgets.QDoubleSpinBox(); self.width.setRange(.1, 1000); self.width.setValue(4)
        self.depth = QtWidgets.QDoubleSpinBox(); self.depth.setRange(.1, 1000); self.depth.setValue(4)
        self.seed = QtWidgets.QDoubleSpinBox(); self.seed.setDecimals(0); self.seed.setRange(0, 4294967295); self.seed.setValue(1)
        self.seconds = QtWidgets.QDoubleSpinBox(); self.seconds.setRange(.1, 120); self.seconds.setValue(12)
        self.height = QtWidgets.QDoubleSpinBox(); self.height.setRange(.01, 1000); self.height.setValue(2)
        self.edges = QtWidgets.QComboBox(); self.edges.addItems(["walls", "open"])
        self.resolution = QtWidgets.QComboBox(); self.resolution.addItems(["256", "512", "1024", "2048"]); self.resolution.setCurrentText("512")
        self.normal = QtWidgets.QComboBox(); self.normal.addItems(["DirectX", "OpenGL"])
        self.scale.hide()  # Compatibility input for older local harnesses; v2 scale belongs to each asset row.
        for label, widget in (("Object count",self.count),("Width (m)",self.width),("Depth (m)",self.depth),("Seed",self.seed),("Time limit (s)",self.seconds),("Height range max (m)",self.height),("Edges",self.edges),("Resolution",self.resolution),("Normal",self.normal)):
            form.addRow(label,widget)
        layout.addLayout(form)
        actions=QtWidgets.QHBoxLayout()
        self.simulate=QtWidgets.QPushButton("Simulate + Bake");self.simulate.clicked.connect(lambda:self.run(False))
        self.rebake=QtWidgets.QPushButton("Bake saved pile");self.rebake.clicked.connect(lambda:self.run(True))
        self.cancel=QtWidgets.QPushButton("Cancel");self.cancel.clicked.connect(self.stop)
        for w in (self.simulate,self.rebake,self.cancel):actions.addWidget(w)
        layout.addLayout(actions)
        self.progress=QtWidgets.QProgressBar();layout.addWidget(self.progress)
        self.preview=QtWidgets.QLabel("Height preview appears after baking");self.preview.setMinimumHeight(150);self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.preview)
        self.status=QtWidgets.QLabel("Open a saved SBS graph and add a scatter.");self.status.setWordWrap(True);layout.addWidget(self.status)
        self.editable_controls=[create,self.nodes,refresh,self.mesh,browse,self.assets,remove,self.mask_enabled,self.mask_path,self.mask_browse,self.count,self.scale,self.width,self.depth,self.seed,self.seconds,self.height,self.edges,self.resolution,self.normal,self.viewer_apply,self.viewer_settings,self.viewer_graph_run]
        self.editable_controls.extend([self.mask_mode,self.source_choices,self.source_refresh,self.source_inspect])
        for widget in (self.mask_mode,self.source_choices,self.source_refresh,self.source_inspect,self.source_status):widget.setVisible(True)
        self.cancel.setEnabled(False)
        layout.addStretch()
        self.refresh()

    def message(self, text):
        self.status.setText(str(text))

    def local_viewer_url(self):
        raw=os.environ.get('SCATTER_REVIEW_PORT','8765')
        if not raw.isascii() or not raw.isdecimal() or not 1024<=int(raw)<=65535:
            raise ValueError('Invalid local viewer port')
        return 'http://127.0.0.1:'+str(int(raw))+'/'

    def open_local_viewer(self):
        self._viewer_start_check(True)

    def check_local_viewer(self):
        self._viewer_start_check(False)

    def open_viewer_settings(self):
        try:
            from .viewer_settings import open_viewer_settings
            open_viewer_settings(self)
        except HOST_ERRORS as error:self.viewer_status.setText('Viewer settings unavailable: '+str(error))

    def _viewer_start_check(self,open_when_ready):
        try:
            if getattr(self,'_viewer_start_state',None) is not None:return
            from . import viewer_runtime,lifecycle
            url=self.local_viewer_url();root=viewer_runtime.checkout_root();port=int(url.split(':')[2].rstrip('/'))
            shared=lifecycle.qt_registry().setdefault('viewer_starts',{})
            state=dict(url=url,root=root,port=port,open=open_when_ready,shared=shared,deadline=time.monotonic()+15,launched=False)
            self._viewer_start_state=state;self.viewer_open.setEnabled(False);self.viewer_check.setEnabled(False)
            self.viewer_status.setText('Checking local viewer…');self._viewer_probe(state)
        except HOST_ERRORS as error:
            state=getattr(self,'_viewer_start_state',None)
            if state is not None:self._viewer_start_finish(state,'Local viewer unavailable: '+str(error))
            else:self.viewer_status.setText(str(error))

    def _viewer_probe(self,state):
        from PySide6 import QtNetwork
        if getattr(self,'_viewer_start_state',None) is not state:return
        if not hasattr(self,'_viewer_network'):self._viewer_network=QtNetwork.QNetworkAccessManager(self)
        request=QtNetwork.QNetworkRequest(QtCore.QUrl(state['url']+'api/viewer-health'));request.setTransferTimeout(2000)
        reply=self._viewer_network.get(request);state['reply']=reply;data=bytearray();oversized=[False]
        def ready():
            data.extend(bytes(reply.readAll()))
            if len(data)>16384 and not oversized[0]:oversized[0]=True;reply.abort()
        def finished():
            try:
                ready()
                if getattr(self,'_viewer_start_state',None) is not state:return
                error=reply.error()
                if error in (QtNetwork.QNetworkReply.NetworkError.ConnectionRefusedError,QtNetwork.QNetworkReply.NetworkError.OperationCanceledError) and not oversized[0]:
                    from . import viewer_runtime
                    if not viewer_runtime.port_is_unbound(state['port']):raise ValueError('Port has a listener whose identity could not be verified; no process was changed')
                    if not state['open']:raise ValueError('Local viewer is not running. Open local 3D viewer to start it.')
                    self._viewer_start_or_wait(state);return
                if error!=QtNetwork.QNetworkReply.NetworkError.NoError or oversized[0]:raise ValueError('Port is occupied or viewer health check failed ('+reply.errorString()+'); no existing process was changed')
                from . import viewer_runtime
                viewer_runtime.validate_health(json.loads(bytes(data)),state['root'])
                state['shared'].pop(state['url'],None)
                if state['open'] and not QtGui.QDesktopServices.openUrl(QtCore.QUrl(state['url'])):raise ValueError('The system could not open the local viewer')
                self._viewer_start_finish(state,'Local viewer ready · local checkout identity only, not authentication. It remains running after Designer closes; results require explicit Apply.')
            except HOST_ERRORS as error:self._viewer_start_finish(state,'Local viewer unavailable: '+str(error))
            finally:reply.deleteLater()
        reply.readyRead.connect(ready);reply.finished.connect(finished)

    def _viewer_start_or_wait(self,state):
        from . import viewer_runtime
        shared=state['shared'];entry=shared.get(state['url'])
        if entry is None:
            # Never infer an empty port from a timeout; check both Windows listener tables again.
            if not viewer_runtime.port_is_unbound(state['port']):raise ValueError('Port became occupied; no process was changed')
            process=viewer_runtime.launch(state['root'],state['port']);state['owned_process']=process;entry={'process':process,'deadline':time.monotonic()+15};shared[state['url']]=entry
            self.viewer_status.setText('Starting local viewer; it will stay open after Designer closes…')
        if time.monotonic()>state['deadline'] or time.monotonic()>entry['deadline']:
            if entry['process'].poll() is not None:shared.pop(state['url'],None)
            raise ValueError('Viewer did not become ready. Check BUILDING.md or start local_review/launch.py --source manually; no process was terminated.')
        QtCore.QTimer.singleShot(250,lambda:self._viewer_probe(state))

    def _viewer_start_finish(self,state,message):
        if getattr(self,'_viewer_start_state',None) is not state:return
        if state.get('owned_process') is not None:self._viewer_last_owned_process=state['owned_process']
        self._viewer_start_state=None;self.viewer_open.setEnabled(True);self.viewer_check.setEnabled(True);self.viewer_status.setText(message)

    def apply_viewer_result(self):
        token=None
        try:
            token=self._begin('viewer_handoff')
            self._operation_context(token)
            from . import designer_external
            token['connections']=designer_external.connection_snapshot(designer.resolve_scatter(token['target']),designer)
            token['viewer_handoff']={'maps':{},'total':0}
            self.message('Checking current viewer result…')
            self._handoff_get(token,'api/state',2*1024*1024,self._handoff_state)
        except HOST_ERRORS as error:
            self.message('Viewer result not applied: '+str(error))
            if token is not None:self._end(token)

    def _handoff_get(self,token,path,limit,callback):
        from PySide6 import QtNetwork
        if not self._valid(token):self._handoff_failure(token,'Operation cancelled or target changed');return
        if not hasattr(self,'_viewer_network'):self._viewer_network=QtNetwork.QNetworkAccessManager(self)
        request=QtNetwork.QNetworkRequest(QtCore.QUrl(self.local_viewer_url()+path));request.setTransferTimeout(10000)
        reply=self._viewer_network.get(request);token['handoff_reply']=reply
        chunks=bytearray();oversized=[False]
        def ready():
            chunks.extend(bytes(reply.readAll()))
            if len(chunks)>limit and not oversized[0]:
                oversized[0]=True;reply.abort()
        def finished():
            try:
                ready()
                if not self._valid(token):
                    self._handoff_failure(token,'Operation cancelled or target changed');return
                if oversized[0]:raise ValueError('Viewer response exceeds limit')
                if reply.error()!=QtNetwork.QNetworkReply.NetworkError.NoError:raise ValueError('Viewer request failed: '+reply.errorString())
                callback(token,bytes(chunks))
            except HOST_ERRORS as error:self._handoff_failure(token,str(error))
            finally:
                if token.get('handoff_reply') is reply:token.pop('handoff_reply',None)
                reply.deleteLater()
                if self._token is token and token.get('cancelled'):self._end(token)
        reply.readyRead.connect(ready);reply.finished.connect(finished)

    def _handoff_state(self,token,raw):
        state=json.loads(raw);current=state.get('current') if isinstance(state,dict) else None
        job=current.get('job_id') if isinstance(current,dict) else None
        if type(job) is not str or not re.fullmatch('[0-9a-f]{32}',job):raise ValueError('No validated current viewer result')
        token['viewer_handoff']['job']=job
        self._handoff_get(token,'api/designer-handoff/'+job,65536,self._handoff_manifest)

    def _handoff_manifest(self,token,raw):
        manifest=json.loads(raw);h=token['viewer_handoff'];job=h['job']
        if not isinstance(manifest,dict) or manifest.get('schema_version')!=1 or manifest.get('job_id')!=job or not isinstance(manifest.get('maps'),dict):raise ValueError('Invalid viewer manifest')
        roles=set(manifest['maps']);base={'height','normal','coverage'};full=base|{'basecolor','roughness','metallic','normal_material'}
        if roles not in (base,full):raise ValueError('Unsupported viewer output channels')
        for role,info in manifest['maps'].items():
            if not isinstance(info,dict) or type(info.get('bytes')) is not int or not 1<=info['bytes']<=16*1024*1024 or type(info.get('sha256')) is not str or not re.fullmatch('[0-9a-f]{64}',info['sha256']):raise ValueError('Invalid viewer output descriptor: '+role)
        if sum(v['bytes'] for v in manifest['maps'].values())>64*1024*1024:raise ValueError('Viewer output exceeds total limit')
        h.update(manifest=manifest,manifest_raw=raw,roles=sorted(roles),index=0)
        self._handoff_next(token)

    def _handoff_next(self,token):
        h=token['viewer_handoff']
        if h['index']==len(h['roles']):
            if not self._valid(token):raise ValueError('Target changed during viewer transfer')
            graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata']);designer.checked_current(graph,token['jobs'])
            h['files']=self._stage_handoff(token)
            self._handoff_get(token,'api/designer-handoff/'+h['job'],65536,self._handoff_confirm);return
        role=h['roles'][h['index']];info=h['manifest']['maps'][role]
        self._handoff_get(token,'api/maps/'+h['job']+'/'+role,info['bytes'],lambda t,data:self._handoff_map(t,role,data))

    def _handoff_map(self,token,role,raw):
        h=token['viewer_handoff'];info=h['manifest']['maps'][role]
        if len(raw)!=info['bytes'] or hashlib.sha256(raw).hexdigest()!=info['sha256']:raise ValueError('Viewer output identity differs: '+role)
        h['maps'][role]=raw;h['index']+=1;self._handoff_next(token)

    def _handoff_confirm(self,token,raw):
        h=token['viewer_handoff']
        if raw!=h['manifest_raw']:raise ValueError('Viewer result changed while reading')
        graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata']);designer.checked_current(graph,token['jobs'])
        if not self._valid(token):raise ValueError('Target changed during viewer transfer')
        files=h['files']
        from . import designer_external
        def guard():
            if not self._valid(token):raise ValueError('Target changed or operation cancelled')
            current=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(current,token['metadata'])
            designer.checked_current(current,token['jobs'])
        def connection_guard():
            current=designer.resolve_scatter(token['target'])
            if designer_external.connection_snapshot(current,designer)!=token['connections']:
                raise ValueError('Designer output connections changed during viewer transfer')
        designer_external.apply_external(graph,h['manifest'],files,guard=guard,connection_guard=connection_guard)
        self.message('Viewer job '+h['job']+' snapshot applied · save the SBS package to keep graph changes')
        self.viewer_status.setText('Applied fixed viewer job '+h['job']+' to '+graph.getIdentifier()+' · later viewer results require Apply again')
        self._end(token)

    def _handoff_failure(self,token,reason):
        if token.get('viewer_graph') is not None:
            value=token['viewer_graph']
            if value.get('run_token'):
                value['cancel_reason']=reason;value['cancel_requested']=True
                if value.get('cancelling'):return
                try:self._viewer_graph_cancel(token);return
                except HOST_ERRORS as error:reason+=' · could not request owned job cancellation: '+str(error)
            self._viewer_graph_failure(token,reason);return
        self.message('Viewer result not applied: '+reason)
        self._end(token)

    def _stage_handoff(self,token):
        from .handoff_paths import owned_external
        h=token['viewer_handoff'];graph=designer.resolve_scatter(token['target'])
        def checked():return owned_external(graph.getPackage().getFilePath(),graph.getIdentifier(),h['job'],token['jobs'].directory)
        target=checked();root=target.parent
        root.mkdir(parents=True,exist_ok=True)
        if checked()!=target:raise ValueError('External output path changed')
        if target.exists():
            if not target.is_dir():raise ValueError('External output path is not a directory')
            for role,raw in h['maps'].items():
                path=target/(role+'.png')
                if path.is_symlink() or not path.is_file() or getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400) or path.stat().st_size!=len(raw) or path.read_bytes()!=raw:raise ValueError('Existing external output differs')
        else:
            temporary=root/('.stage-'+uuid.uuid4().hex);temporary.mkdir()
            for role,raw in h['maps'].items():
                with (temporary/(role+'.png')).open('xb') as stream:stream.write(raw)
            if checked()!=target:raise ValueError('External output path changed during staging')
            temporary.rename(target)
        if checked()!=target:raise ValueError('External output path changed before apply')
        return {role:target/(role+'.png') for role in h['maps']}

    def run_viewer_graph(self):
        token=None
        try:
            if not self._graph_ui_enabled or self._source_selection is None or self._source_context is None:
                raise ValueError('Select and inspect a supported Graph terminal first')
            token=self._begin('viewer_graph');current=self._operation_context(token)
            self.cancel.setEnabled(False);self.viewer_graph_cancel.setEnabled(True)
            token['viewer_graph']={'selection':copy.deepcopy(self._source_selection),'context':copy.deepcopy(self._source_context),
                'forbidden':list((current or {}).get('files',{}).values()),'cancel_requested':False}
            self.viewer_draft_status.setText('Reading explicitly submitted viewer settings…')
            self._handoff_get(token,'api/state',2*1024*1024,self._viewer_graph_state)
        except HOST_ERRORS as error:
            self.message('Graph viewer simulation not started: '+str(error))
            if token is not None:self._end(token)

    def _viewer_graph_state(self,token,raw):
        state=json.loads(raw);session=state.get('session_token') if isinstance(state,dict) else None
        if type(session) is not str or not re.fullmatch('[0-9a-f]{64}',session):raise ValueError('Viewer session token missing')
        token['viewer_graph']['session']=session
        self._handoff_get(token,'api/designer-draft',1024*1024,self._viewer_graph_draft)

    def _viewer_graph_draft(self,token,raw):
        draft=json.loads(raw);revision=draft.get('revision') if isinstance(draft,dict) else None
        settings=draft.get('settings') if isinstance(draft,dict) else None
        if type(revision) is not str or not re.fullmatch('[0-9a-f]{32}',revision) or not isinstance(settings,dict) or not isinstance(settings.get('assets'),list) or not settings['assets'] or not isinstance(settings.get('simulation'),dict) or not isinstance(settings.get('bake'),dict):raise ValueError('Viewer settings were not submitted or are invalid')
        current=draft.get('current_job_id')
        if current is not None and (type(current) is not str or not re.fullmatch('[0-9a-f]{32}',current)):raise ValueError('Viewer current job identity differs')
        value=token['viewer_graph'];value['draft']=copy.deepcopy(draft)
        simulation=settings['simulation'];bake=settings['bake']
        self.viewer_draft_status.setText('Submitted revision '+revision+' · '+str(len(settings['assets']))+' assets · count '+str(simulation.get('count'))+' · seed '+str(simulation.get('seed'))+' · '+str(simulation.get('edges'))+' · '+str(bake.get('resolution'))+' px. Each new run recaptures Graph; Saved reuses its mask.')
        self.message('Capturing inspected Graph; cancellation is handled after SDK return…')
        QtCore.QTimer.singleShot(0,lambda:self._viewer_graph_capture(token))

    def _viewer_graph_capture(self,token):
        try:
            if not self._valid(token):self._end(token);return
            value=token['viewer_graph'];graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata'])
            designer.checked_current(graph,token['jobs'])
            captured=designer.capture_terminal(value['selection'],value['context'],token['id'],self._capture_directory(token),value['forbidden'])
            if not self._valid(token):self._end(token);return
            packet={k:captured[k] for k in ('png','capture','operation_authored_payload')}
            from .core import _validated_capture
            from .fileio import io_path
            _validated_capture(packet)
            png=io_path(packet['png']['path']).read_bytes()
            if len(png)!=packet['png']['bytes'] or hashlib.sha256(png).hexdigest()!=packet['png']['sha256']:raise ValueError('Captured Graph PNG changed')
            claim=copy.deepcopy(packet);claim['png'].pop('path')
            claim_raw=json.dumps(claim,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
            if len(claim_raw)>1024*1024:raise ValueError('Graph capture provenance exceeds limit')
            value.update(png_sha=packet['png']['sha256'],claim_sha=hashlib.sha256(claim_raw).hexdigest())
            self._viewer_graph_upload(token,png,claim_raw)
        except HOST_ERRORS as error:
            detail=str(error)
            if isinstance(error,OSError) and getattr(error,'winerror',None)==206:
                detail='Graph capture path exceeds Windows/tool limits; use a shorter SBS location until long-path support is verified'
            self._viewer_graph_failure(token,detail)

    def _viewer_graph_upload(self,token,png,claim):
        from PySide6 import QtNetwork
        if not self._valid(token):self._end(token);return
        multi=QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.ContentType.FormDataType)
        part=QtNetwork.QHttpPart();part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentDispositionHeader,'form-data; name="file"; filename="graph-mask.png"');part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader,'image/png');part.setBody(QtCore.QByteArray(png));multi.append(part)
        part=QtNetwork.QHttpPart();part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentDispositionHeader,'form-data; name="capture_json"');part.setBody(QtCore.QByteArray(claim));multi.append(part)
        self._viewer_graph_post(token,'api/graph-mask',multi,self._viewer_graph_uploaded)

    def _viewer_graph_uploaded(self,token,raw):
        value=token['viewer_graph'];uploaded=json.loads(raw)
        if not isinstance(uploaded,dict) or not re.fullmatch('[0-9a-f]{32}',str(uploaded.get('mask_id',''))) or uploaded.get('sha256')!=value['png_sha'] or uploaded.get('provenance_sha256')!=value['claim_sha']:raise ValueError('Graph mask upload identity differs')
        if not self._valid(token):self._end(token);return
        graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata']);designer.checked_current(graph,token['jobs'])
        # Reinspect the authored source after upload; an edit cannot silently reuse old pixels.
        current=designer.inspect_terminal_selection(value['selection'],uuid.uuid4().hex,self._capture_directory(token),value['forbidden'])
        if current['selected_context']!=value['context'] or not self._valid(token):raise ValueError('Graph changed since Inspect; inspect it again')
        draft=value['draft'];settings=copy.deepcopy(draft['settings']);settings['mask_id']=uploaded['mask_id'];settings['graph_mask_provenance_sha256']=uploaded['provenance_sha256'];settings['designer_draft_revision']=draft['revision'];settings['expected_current_job_id']=draft.get('current_job_id')
        value['submit_pending']=True
        self._viewer_graph_post(token,'api/run',json.dumps(settings,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8'),self._viewer_graph_started)

    def _viewer_graph_post(self,token,path,payload,callback,*,cancel=False):
        from PySide6 import QtNetwork
        if self._token is not token:raise ValueError('Panel operation no longer owned')
        if not hasattr(self,'_viewer_network'):self._viewer_network=QtNetwork.QNetworkAccessManager(self)
        request=QtNetwork.QNetworkRequest(QtCore.QUrl(self.local_viewer_url()+path));request.setTransferTimeout(15000)
        request.setRawHeader(b'X-Review-Token',token['viewer_graph']['session'].encode('ascii'))
        if isinstance(payload,bytes):request.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json');payload=QtCore.QByteArray(payload)
        reply=self._viewer_network.post(request,payload);token['handoff_reply']=reply
        if isinstance(payload,QtNetwork.QHttpMultiPart):payload.setParent(reply)
        chunks=bytearray();oversized=[False]
        def ready():
            chunks.extend(bytes(reply.readAll()))
            if len(chunks)>1024*1024 and not oversized[0]:oversized[0]=True;reply.abort()
        def finished():
            try:
                ready()
                if self._token is not token:return
                if oversized[0] or reply.error()!=QtNetwork.QNetworkReply.NetworkError.NoError:raise ValueError('Viewer request failed: '+reply.errorString())
                if not cancel and not token['viewer_graph'].get('submit_pending') and not self._valid(token):raise ValueError('Panel target changed or operation cancelled')
                callback(token,bytes(chunks))
            except HOST_ERRORS as error:self._viewer_graph_failure(token,str(error))
            finally:
                if token.get('handoff_reply') is reply:token.pop('handoff_reply',None)
                reply.deleteLater()
        reply.readyRead.connect(ready);reply.finished.connect(finished)

    def _viewer_graph_started(self,token,raw):
        value=token['viewer_graph'];value['submit_pending']=False;response=json.loads(raw);run_token=response.get('token') if isinstance(response,dict) else None
        if type(run_token) is not str or not re.fullmatch('[0-9a-f]{32}',run_token):raise ValueError('Viewer execution token missing')
        value['run_token']=run_token
        if value['cancel_requested'] or not self._valid(token):self._viewer_graph_cancel(token);return
        self.message('Viewer simulation started from submitted settings; prior result remains until success.')
        QtCore.QTimer.singleShot(250,lambda:self._viewer_graph_poll(token))

    def _viewer_graph_poll(self,token):
        if self._token is not token:return
        value=token['viewer_graph']
        if value['cancel_requested'] or not self._valid(token):self._viewer_graph_cancel(token);return
        self._handoff_get(token,'api/state',2*1024*1024,self._viewer_graph_polled)

    def _viewer_graph_polled(self,token,raw):
        state=json.loads(raw);job=state.get('job',{});value=token['viewer_graph']
        if job.get('token')!=value['run_token']:raise ValueError('Viewer job identity changed; check viewer status')
        status=job.get('status')
        if status in ('queued','preparing','running','cancelling'):
            self.message('Viewer simulation: '+status+' · Graph mask captured for revision '+value['draft']['revision']);QtCore.QTimer.singleShot(250,lambda:self._viewer_graph_poll(token));return
        if status=='completed':self.message('Viewer simulation completed. Inspect the result, then apply it to Designer explicitly.')
        else:self.message('Viewer simulation '+str(status)+': '+str(job.get('error') or '')+' · check previous result in viewer')
        self._end(token)

    def _viewer_graph_cancel(self,token):
        value=token['viewer_graph'];run_token=value.get('run_token')
        if not run_token or value.get('cancelling'):return
        value['cancelling']=True
        self._viewer_graph_post(token,'api/cancel/'+run_token,b'{}',self._viewer_graph_cancelled,cancel=True)

    def _viewer_graph_cancelled(self,token,raw):
        value=token['viewer_graph'];response=json.loads(raw)
        if not isinstance(response,dict) or response.get('token')!=value.get('run_token') or response.get('status')!='cancelling':raise ValueError('Viewer cancellation acknowledgement differs')
        self.message('Viewer cancellation requested for the owned job; final status is not yet confirmed. It may already have completed; check the viewer.')
        self._end(token)

    def _viewer_graph_failure(self,token,reason):
        value=token.get('viewer_graph',{})
        if value.get('submit_pending'):reason+=' · submission outcome unknown; check the viewer before retrying'
        elif value.get('run_token'):reason+=' · job status or cancellation is unconfirmed and it may have completed; check the viewer before retrying'
        self.message('Graph viewer operation stopped: '+reason)
        self._end(token)

    def browse(self):
        typed=self.mesh.text().strip()
        if typed and Path(typed).is_file():paths=[typed]
        else:paths,_=QtWidgets.QFileDialog.getOpenFileNames(self,"Add OBJ assets","","OBJ (*.obj)")
        for path in paths:self.add_asset({"path":path,"weight":1.0,"scale":.3})
        if paths:self.mesh.clear()

    def browse_mask(self):
        if self.process or self._token:return
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,"Choose grayscale scatter mask","","PNG (*.png)")
        if path:self.set_mask({"enabled":True,"path":path,"source_name":Path(path).name})

    def set_mask(self,config):
        if self.process or self._token:raise ValueError("Wait for the active operation")
        value=dict(config or {});value.setdefault("enabled",bool(config));self._mask_config={key:value[key] for key in ("enabled","path","content_hash","source_name") if key in value}
        self.mask_enabled.setChecked(value["enabled"])
        name=value.get("source_name",Path(value.get("path","")).name)
        self.mask_path.setText(name);self.mask_path.setToolTip(value.get("path",""))
        self.mask_snapshot.setText(("Saved mask: "+name if value.get("content_hash") else "Selected mask: "+name) if name else "A mask controls starting centers; physics may move objects outside it.")

    def mask_config(self):
        return dict(self._mask_config,enabled=self.mask_enabled.isChecked())

    def set_busy(self,value):
        for widget in self.editable_controls:widget.setEnabled(not value)
        for widget in (self.mask_mode,self.source_choices,self.source_refresh,self.source_inspect):widget.setEnabled(not value and self._graph_ui_enabled)
        self.simulate.setEnabled(not value);self.rebake.setEnabled(not value);self.cancel.setEnabled(value)

    def add_asset(self, asset):
        index=self.assets.rowCount();self.assets.insertRow(index)
        identity=dict(asset);identity.setdefault("asset_id",uuid.uuid4().hex);identity.setdefault("format","obj")
        identity.setdefault("source_name",Path(identity["path"]).name)
        for column,key in enumerate(("path","weight","scale")):
            item=QtWidgets.QTableWidgetItem(str(identity.get(key,1)))
            if column==0:
                item.setText(identity["source_name"])
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                item.setData(QtCore.Qt.ItemDataRole.UserRole,identity)
                item.setToolTip(identity["path"]+"\nasset_id: "+identity["asset_id"])
            self.assets.setItem(index,column,item)

    def remove_asset(self):
        for index in sorted({item.row() for item in self.assets.selectedItems()},reverse=True):self.assets.removeRow(index)

    def asset_rows(self):
        rows=[]
        for index in range(self.assets.rowCount()):
            item=self.assets.item(index,0);row=dict(item.data(QtCore.Qt.ItemDataRole.UserRole))
            row.update(weight=float(self.assets.item(index,1).text()),scale=float(self.assets.item(index,2).text()))
            rows.append(row)
        return rows

    def set_assets(self, rows):
        self.assets.setRowCount(0)
        for row in rows:self.add_asset(row)

    def refresh(self):
        if self.process or self._token:return
        try:self._refresh()
        except HOST_ERRORS as error:self.nodes.blockSignals(False);self.message(error)

    def _refresh(self):
        selected=self.nodes.currentText();self.nodes.blockSignals(True);self.nodes.clear()
        for package in designer.application().getPackageMgr().getUserPackages():
            for resource in package.getChildrenResources(True):
                if isinstance(resource,designer.SDSBSCompGraph) and designer.settings(resource):
                    self.nodes.addItem(resource.getIdentifier(),resource)
        if selected:self.nodes.setCurrentText(selected)
        self.nodes.blockSignals(False);self.select()

    def add(self):
        try:
            if self.process or self._token:raise ValueError("Wait for the current operation")
            parent=designer.application().getQtForPythonUIMgr().getCurrentGraph()
            if parent is None:raise ValueError("Open a saved compositing graph first")
            graph,_=designer.create(parent);self.refresh();self.nodes.setCurrentText(graph.getIdentifier())
        except HOST_ERRORS as error:self.message(error)

    def select(self,*_):
        try:self._select()
        except HOST_ERRORS as error:self.message(error)

    def _select(self):
        if self.process or self._token:
            self._select_again=True;self.stop();return
        self.invalidate_source()
        self.graph=self.nodes.currentData()
        self._target_identity=None
        self.viewer_target.setText('Designer target: '+(self.graph.getIdentifier() if self.graph is not None else 'no scatter selected'))
        self.preview.clear()
        self.viewer_status.setText('Local viewer runs separately. Its assets and results are not automatically applied to the selected Designer graph.')
        if self.graph is None:return
        self._target_identity=designer.scatter_identity(self.graph)
        self.jobs=Jobs(designer.result_directory(self.graph))
        state=designer.settings(self.graph) or {}
        config=state.get("config",{})
        self.mesh.setText(config.get("mesh",""))
        s=config.get("simulation",{});b=config.get("bake",{})
        for k,w in (("count",self.count),("scale",self.scale),("width",self.width),("depth",self.depth),("seed",self.seed),("seconds",self.seconds)):
            if k in s:w.setValue(s[k])
        self.edges.setCurrentText(s.get("edges","walls"));self.resolution.setCurrentText(str(b.get("resolution",512)));self.normal.setCurrentText(b.get("normal","DirectX"));self.height.setValue(b.get("height_max",2))
        current=designer.checked_current(self.graph,self.jobs)
        self.set_mask(config.get("scatter_mask",current["request"].get("scatter_mask") if current else None))
        rows=config.get("assets",[])
        if current and current["request"].get("schema_version",1)==2:
            cached={row["asset_id"]:row for row in current["request"]["assets"]}
            rows=rows or list(cached.values())
            rows=[dict(row,path=(row["path"] if Path(row["path"]).is_file() else cached[row["asset_id"]]["path"])) for row in rows]
        elif not rows and self.mesh.text():
            path=self.mesh.text()
            if current and not Path(path).is_file():path=current["request"]["asset_path"]
            rows=[{"asset_id":"00000000000000000000000000000001","path":path,"weight":1.0,"scale":s.get("scale",.3),"format":"obj"}]
        self.set_assets(rows)
        self.mask_mode.setCurrentText(config.get('mask_source_mode','File / no mask'))
        self.source_status.setText('Select and inspect the source again; saved contexts are historical.')
        external=state.get('external_current')
        if external:
            self.preview.clear()
            self.viewer_status.setText('Applied viewer job '+str(external.get('job_id','unknown'))+' · Designer Simulate/Bake requires another scatter node.')
            try:
                from . import designer_external
                manifest=external['manifest'];directory=designer_external.owned_stage(self.graph,external['job_id'],designer)
                files={role:directory/(role+'.png') for role in manifest['maps']}
                designer_external.verify_files(self.graph,manifest,files,designer)
                self.show_preview({'files':files})
            except HOST_ERRORS as error:self.viewer_status.setText('Applied viewer result unavailable: '+str(error))
        elif current:self.show_preview(current)

    def show_preview(self,candidate):
        image=QtGui.QPixmap(candidate["files"]["height"])
        self.preview.setPixmap(image.scaled(300,220,QtCore.Qt.AspectRatioMode.KeepAspectRatio,QtCore.Qt.TransformationMode.SmoothTransformation))

    def invalidate_source(self,*_):
        self._source_revision+=1;self._source_selection=None;self._source_context=None
        if self._token:self.stop()

    def enable_graph_ui_for_testing(self,enabled=False):
        """Per-panel test override; normal panels expose the accepted Graph UI."""
        if type(enabled) is not bool:raise ValueError('Graph UI development flag must be bool')
        if self._token or self.process:raise ValueError('Wait for the current operation')
        self.invalidate_source();self._graph_ui_enabled=enabled
        self.mask_mode.clear();self.mask_mode.addItems(['File / no mask']+(['Graph terminal'] if enabled else []))
        for widget in (self.mask_mode,self.source_choices,self.source_refresh,self.source_inspect,self.source_status):widget.setVisible(enabled)
        self.source_status.setText('Choose a terminal and inspect it. Run captures fresh pixels.')
        self.set_busy(False)

    def resume(self):
        if self._token or self.process:raise ValueError('Wait for the current operation')
        self._closing=False;self.invalidate_source()

    def refresh_sources(self):
        if self._token or self.process:return
        try:
            if not self._graph_ui_enabled:raise ValueError('Graph UI is disabled pending live acceptance')
            choices=designer.terminal_selections();self.source_choices.clear()
            for value in choices:self.source_choices.addItem(value['graph_identifier']+' / '+value['terminal_identifier'],value)
            self.source_status.setText('Choose a terminal and inspect it. Inspection performs no compute.')
        except HOST_ERRORS as error:self.message(error)

    def _begin(self,phase):
        if self._closing or getattr(self,'_lifecycle_stopping',False):raise ValueError('Panel is shutting down')
        if self.process or self._token:raise ValueError('Wait for the current operation')
        if self.graph is None or self.jobs is None:raise ValueError('Select a scatter node first')
        token=dict(id=uuid.uuid4().hex,generation=self._generation,target=copy.deepcopy(self._target_identity),source_revision=self._source_revision,jobs=self.jobs,job_id=None,cancelled=False)
        self._token=token;self._phase=phase;self.set_busy(True)
        return token

    def _valid(self,token):
        owned_job=token['job_id'] is None or (token['jobs'].active is not None and token['jobs'].active['job_id']==token['job_id'])
        return self._token is token and token['generation']==self._generation and token['jobs'] is self.jobs and owned_job and token['target']==self._target_identity and token['source_revision']==self._source_revision and not token['cancelled'] and not self._closing and not getattr(self,'_lifecycle_stopping',False)

    def _cancel_owned(self,token):
        if token is not None and token.get('job_id') is not None and token['jobs'].active is not None and token['jobs'].active['job_id']==token['job_id']:token['jobs'].cancel()

    def _end(self,token):
        if self._token is not token:return
        if hasattr(self,'viewer_graph_cancel'):self.viewer_graph_cancel.setEnabled(False)
        if token.get('live_registered'):
            timer=getattr(self,'_live_timer',None)
            if timer is not None:timer.stop()
            try:live_preview.finish(token['jobs'].directory,token['id'],token.get('live_outcome','cancelled' if token['cancelled'] else 'failed'))
            except HOST_ERRORS as error:self.message('LIVE 종료 상태 기록 실패: '+str(error))
        self._token=None;self._phase='idle';self.pending_config=None
        if not self._closing and not getattr(self,'_lifecycle_stopping',False):self.set_busy(False)
        if self._select_again and not self._closing:
            self._select_again=False;QtCore.QTimer.singleShot(0,self.select)
        self._try_shutdown_acks()

    def _try_shutdown_acks(self):
        if self._token is not None or self.process is not None or getattr(self,'_settings_shutdown_pending',False):return
        callbacks=self._shutdown_acks;self._shutdown_acks=[]
        for callback in callbacks:callback()

    def _operation_context(self,token):
        graph=designer.resolve_scatter(token['target']);current=designer.checked_current(graph,token['jobs'])
        token['metadata']=copy.deepcopy(designer.settings(graph) or {})
        return current

    def _capture_directory(self,token):
        directory=Path(token['jobs'].directory)/'terminal_operations';directory.mkdir(parents=True,exist_ok=True)
        return directory

    def _ensure_live(self):
        if getattr(self,'_live_timer',None) is None:
            self._live_timer=QtCore.QTimer(self);self._live_timer.setInterval(250)
            self._live_timer.timeout.connect(self._live_heartbeat)
    def _live_started(self,token,process):
        if not self._owns_process(token,process):return
        try:
            if not self._valid(token):process.kill();return
            live_preview.heartbeat(token['jobs'].directory,token['id'],int(process.processId()))
            token['live_started_monotonic']=time.monotonic()
            self._ensure_live();self._live_timer.start()
        except HOST_ERRORS as error:
            token['live_outcome']='failed';token['cancelled']=True;process.kill();self.message('LIVE 시작 거부: '+str(error))
    def _live_heartbeat(self):
        token=self._token;process=self.process
        if token is None or process is None or not token.get('live_registered'):
            self._live_timer.stop();return
        if process.state()==QtCore.QProcess.ProcessState.NotRunning:return
        if not self._valid(token):process.kill();return
        if time.monotonic()-token.get('live_started_monotonic',time.monotonic())>=180:
            self._live_timeout(token,process);return
        try:live_preview.heartbeat(token['jobs'].directory,token['id'],int(process.processId()))
        except HOST_ERRORS as error:
            token['live_outcome']='failed';token['cancelled']=True;process.kill();self.message('LIVE 소유권 거부: '+str(error))
    def _live_timeout(self,token,process):
        if self._owns_process(token,process) and process.state()!=QtCore.QProcess.ProcessState.NotRunning:
            token['live_outcome']='failed';token['cancelled']=True;process.kill();self.message('LIVE 물리+베이크180초 제한; 이전 결과 보존')

    def inspect_source(self):
        token=None
        try:
            if not self._graph_ui_enabled:raise ValueError('Graph UI is disabled pending live acceptance')
            selected=copy.deepcopy(self.source_choices.currentData())
            if selected is None:raise ValueError('List and select a source terminal first')
            token=self._begin('inspecting');current=self._operation_context(token)
            self._source_selection=None;self._source_context=None
            self.source_status.setText('Inspecting synchronously; cancellation is handled after SDK return.')
            result=designer.inspect_terminal_selection(selected,token['id'],self._capture_directory(token),list((current or {}).get('files',{}).values()))
            self._phase='awaiting_continuation'
            QtCore.QTimer.singleShot(0,lambda:self._inspection_ready(token,selected,result))
        except HOST_ERRORS as error:
            self.message(error)
            if token is not None:self._end(token)

    def _inspection_ready(self,token,selected,result):
        try:
            if not self._valid(token):return
            graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata']);designer.checked_current(graph,token['jobs'])
            self._source_selection=copy.deepcopy(selected);self._source_context=copy.deepcopy(result['selected_context'])
            self.mask_mode.setCurrentText('Graph terminal');self.source_status.setText('Inspected. Run captures a fresh terminal PNG; it never reuses previous pixels.')
        except HOST_ERRORS as error:self.message(error)
        finally:self._end(token)

    def run(self,rebake):
        token=None
        try:
            token=self._begin('preparing')
            graph=designer.resolve_scatter(token['target'])
            if (designer.settings(graph) or {}).get('external_current'):
                raise ValueError('This graph has an applied viewer result. Create another scatter node for Designer Simulate/Bake to avoid mixing channels.')
            executable=worker_path()
            s={"count":self.count.value(),"width":self.width.value(),"depth":self.depth.value(),"seed":int(self.seed.value()),"seconds":self.seconds.value(),"edges":self.edges.currentText()}
            current=self._operation_context(token)
            saved_sim=current["request"].get("simulation",{}) if current else {}
            s.update(friction=saved_sim.get("friction",.6),restitution=saved_sim.get("restitution",.05))
            b={"resolution":int(self.resolution.currentText()),"height_min":0,"height_max":self.height.value(),"normal":self.normal.currentText(),"samples":2}
            rows=self.asset_rows()
            if not rows and self.mesh.text():
                rows=[{"asset_id":"00000000000000000000000000000001","path":self.mesh.text(),"weight":1.0,"scale":self.scale.value(),"format":"obj"}]
            mask_config=self.mask_config()
            from . import compat
            from .core import validate_weights
            import math
            compat.simulation(s,version=2)
            if not rows:raise ValueError('Choose at least one OBJ asset')
            for row in rows:
                if not Path(row['path']).is_file() or not math.isfinite(row['scale']) or not .001<=row['scale']<=100 or not math.isfinite(row['weight']) or row['weight']<0:raise ValueError('Invalid asset path, scale or weight')
            validate_weights(rows)
            packet=None;mode='saved_input' if rebake else ('current_graph_terminal' if self.mask_mode.currentText()=='Graph terminal' else 'current_file')
            if mode=='current_graph_terminal':
                if not self._graph_ui_enabled:raise ValueError('Graph UI is disabled pending live acceptance')
                if self._source_selection is None or self._source_context is None:raise ValueError('Select and inspect the graph terminal again')
                self._phase='capturing';self.message('Capturing synchronously; cancel is handled after SDK return.')
                captured=designer.capture_terminal(copy.deepcopy(self._source_selection),copy.deepcopy(self._source_context),token['id'],self._capture_directory(token),list((current or {}).get('files',{}).values()))
                packet={k:captured[k] for k in ('png','capture','operation_authored_payload')}
            self._phase='awaiting_continuation'
            QtCore.QTimer.singleShot(0,lambda:self._prepare_and_start(token,rows,s,b,mask_config,rebake,mode,packet,executable))
        except HOST_ERRORS as error:
            self.message(error)
            if token is not None:self._end(token)

    def _prepare_and_start(self,token,rows,s,b,mask_config,rebake,mode,packet,executable):
        try:
            if not self._valid(token):return
            graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata']);designer.checked_current(graph,token['jobs'])
            self._phase='preparing'
            kwargs=dict(rebake=rebake,host_mode=mode)
            if mode=='current_graph_terminal':kwargs.update(captured_mask=packet,scatter_mask=None)
            elif mode=='current_file':kwargs['scatter_mask']=mask_config
            path=token['jobs'].prepare(rows,s,b,**kwargs)
            token['job_id']=token['jobs'].active['job_id']
            if not self._valid(token):self._cancel_owned(token);return
            hashes={row["asset_id"]:row["content_hash"] for row in self.jobs.active["assets"]}
            self.pending_config={"assets":[dict(row,content_hash=hashes[row["asset_id"]]) for row in rows],"simulation":s,"bake":b}
            if self.jobs.active.get("scatter_mask"):
                saved=self.jobs.active["scatter_mask"];mask_config.update(content_hash=saved["content_hash"],source_name=saved["source_name"])
            self.pending_config["scatter_mask"]=mask_config
            self.pending_config['mask_source_mode']=self.mask_mode.currentText()
            self.buffer=bytearray();self.completed=None
            process=QtCore.QProcess(self);self.process=process;self._phase='running'
            if not rebake and Path(executable).name=='scatter_worker_legacy_live.exe':
                live_preview.begin(self.jobs.directory,self.jobs.active,token['id'],executable,'graph');token['live_registered']=True
                environment=QtCore.QProcessEnvironment.systemEnvironment();environment.insert('SCATTER_LIVE_PREVIEW','1');environment.insert('SCATTER_LIVE_NONCE',token['id']);environment.insert('SCATTER_LIVE_WAIT_READY','1');process.setProcessEnvironment(environment)
                process.started.connect(lambda:self._live_started(token,process))
            process.readyReadStandardOutput.connect(lambda:self._read(token,process))
            process.readyReadStandardError.connect(lambda:self._stderr(token,process))
            process.finished.connect(lambda code,status:self._finish(token,process,code,status))
            process.errorOccurred.connect(lambda error:self._process_error(token,process,error))
            if not self._valid(token):self._cancel_owned(token);self.process=None;process.deleteLater();return
            process.start(str(executable),[str(path)])
        except HOST_ERRORS as error:
            self._cancel_owned(token);self.message(error)
            if self._token is token and self.process is not None:
                process=self.process
                if process.state()==QtCore.QProcess.ProcessState.NotRunning:self.process=None;process.deleteLater()
                else:token['cancelled']=True;process.kill()
        finally:
            if self._token is token and self.process is None:self._end(token)

    def _owns_process(self,token,process):return self._token is token and self.process is process

    def _stderr(self,token,process):
        if self._owns_process(token,process):self.message(bytes(process.readAllStandardError()).decode('utf-8',errors='replace'))

    def process_error(self,error):
        if self.process is not None:self._process_error(self._token,self.process,error)

    def _process_error(self,token,process,error):
        if not self._owns_process(token,process):return
        self.message("Worker process error: "+str(error))
        if error==QtCore.QProcess.ProcessError.FailedToStart:
            self._cancel_owned(token);self.process=None;process.deleteLater();self._end(token)

    def read(self):
        if self.process is not None:self._read(self._token,self.process)

    def _read(self,token,process):
        if not self._owns_process(token,process):return
        self.buffer.extend(bytes(process.readAllStandardOutput()))
        while b"\n" in self.buffer:
            line,_,self.buffer=self.buffer.partition(b"\n")
            try:
                value=json.loads(line)
                if not self._valid(token) or not self.jobs.active or value.get("job_id")!=token['job_id']:continue
                if value["event"]=="progress":self.progress.setValue(int(value["fraction"]*100));self.message(value["stage"])
                elif value["event"]=="completed":self.completed=value
                elif value["event"]=="error":self.message(value["message"])
            except HOST_ERRORS as error:self.message("Invalid worker event: "+str(error))

    def finish(self,code,status):
        if self.process is not None:self._finish(self._token,self.process,code,status)

    def _finish(self,token,process,code,status):
        if not self._owns_process(token,process):return
        self._read(token,process)
        try:
            self._phase='finishing'
            if self._valid(token) and code==0 and self.completed:
                graph=designer.resolve_scatter(token['target']);designer.require_metadata_unchanged(graph,token['metadata']);designer.checked_current(graph,token['jobs'])
                candidate=self.jobs.validate(self.completed["result_path"],self.completed["job_id"])
                rollback=designer.update(graph,candidate,self.pending_config)
                try:
                    if not self._valid(token):raise ValueError('Operation invalidated before promotion')
                    designer.verify_metadata_current(graph,self.jobs,candidate)
                    self.jobs.promote(candidate)
                    token['live_outcome']='completed'
                except HOST_ERRORS as error:
                    rollback_or_raise(error,rollback)
                self.show_preview(candidate);self.progress.setValue(100)
                self._mask_config=dict(self.pending_config.get("scatter_mask",{}))
                if self._mask_config.get("content_hash"):self.mask_snapshot.setText("Saved mask: "+self._mask_config.get("source_name","mask"))
                result=candidate["result"];message="Done · "+result["settling_status"]
                if "spawn_status" in result:
                    reasons={"requested_count_reached":"requested count reached","attempts_exhausted":"mask placement limit","initial_height_limit":"initial height limit","all_black":"mask is fully black"}
                    message="Created "+str(result["spawned_count"])+" of "+str(result["requested_count"])+" · "+result["spawn_status"]+" · "+reasons[result["spawn_stop_reason"]]
                message+=" · save the SBS package to keep graph changes"
                if candidate["result"]["maps"]["clipped_samples"]:
                    message+=" · Height range clipped samples; increase the range and bake again."
                self.message(message)
            elif self.jobs.active:self.message("Worker failed; previous result retained")
        except HOST_ERRORS as error:self.message("Result rejected: "+str(error))
        finally:
            self._cancel_owned(token);self.process=None;process.deleteLater();self._end(token)

    def stop(self):
        token=self._token
        if token is not None and token.get('viewer_graph') is not None:
            value=token['viewer_graph'];value['cancel_requested']=True
            if value.get('submit_pending'):
                self.message('Waiting for viewer submission response to cancel the owned job…');return
            if value.get('run_token'):
                self._viewer_graph_cancel(token);return
        if token is not None:token['cancelled']=True;self._cancel_owned(token)
        if token is not None and token.get('handoff_reply') is not None:
            token['handoff_reply'].abort()
        if token is not None and token.get('live_registered'):
            try:live_preview.finish(token['jobs'].directory,token['id'],'cancelled')
            except HOST_ERRORS as error:self.message('LIVE 취소 상태 기록 실패: '+str(error))
        if self.process:
            self.process.kill();self.message("Cancelled; previous result retained")
        elif token is not None:self.message('Cancellation queued; waiting for the SDK/continuation to return.')

    def request_shutdown(self,callback):
        self._closing=True;self._shutdown_acks.append(callback)
        dialog=getattr(self,'_viewer_settings_dialog',None)
        if dialog is not None and not getattr(self,'_settings_shutdown_pending',False):
            self._settings_shutdown_pending=True
            def dialog_stopped():
                if not getattr(self,'_settings_shutdown_pending',False):return
                self._settings_shutdown_pending=False;self._try_shutdown_acks()
            try:
                shutdown=getattr(dialog,'request_shutdown',None)
                if not callable(shutdown):raise RuntimeError('Viewer settings cannot acknowledge safe shutdown')
                shutdown(dialog_stopped)
            except HOST_ERRORS as error:
                # Keep the lifecycle latched rather than dispose a dialog with an unknown operation.
                self.message('Viewer settings shutdown could not be confirmed: '+str(error))
        self.stop();self._try_shutdown_acks()

    def closeEvent(self,event):
        self._closing=True;self.stop();super().closeEvent(event)
