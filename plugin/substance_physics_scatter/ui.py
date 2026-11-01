from __future__ import annotations
import json
import copy
import uuid
import time
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
        self.editable_controls=[create,self.nodes,refresh,self.mesh,browse,self.assets,remove,self.mask_enabled,self.mask_path,self.mask_browse,self.count,self.scale,self.width,self.depth,self.seed,self.seconds,self.height,self.edges,self.resolution,self.normal]
        self.editable_controls.extend([self.mask_mode,self.source_choices,self.source_refresh,self.source_inspect])
        for widget in (self.mask_mode,self.source_choices,self.source_refresh,self.source_inspect,self.source_status):widget.setVisible(True)
        self.cancel.setEnabled(False)
        layout.addStretch()
        self.refresh()

    def message(self, text):
        self.status.setText(str(text))

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
        if current:self.show_preview(current)

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
        if token.get('live_registered'):
            timer=getattr(self,'_live_timer',None)
            if timer is not None:timer.stop()
            try:live_preview.finish(token['jobs'].directory,token['id'],token.get('live_outcome','cancelled' if token['cancelled'] else 'failed'))
            except HOST_ERRORS as error:self.message('LIVE 종료 상태 기록 실패: '+str(error))
        self._token=None;self._phase='idle';self.pending_config=None
        if not self._closing and not getattr(self,'_lifecycle_stopping',False):self.set_busy(False)
        if self._select_again and not self._closing:
            self._select_again=False;QtCore.QTimer.singleShot(0,self.select)
        if self.process is None:
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
        if token is not None:token['cancelled']=True;self._cancel_owned(token)
        if token is not None and token.get('live_registered'):
            try:live_preview.finish(token['jobs'].directory,token['id'],'cancelled')
            except HOST_ERRORS as error:self.message('LIVE 취소 상태 기록 실패: '+str(error))
        if self.process:
            self.process.kill();self.message("Cancelled; previous result retained")
        elif token is not None:self.message('Cancellation queued; waiting for the SDK/continuation to return.')

    def request_shutdown(self,callback):
        self._closing=True;self._shutdown_acks.append(callback);self.stop()
        if self._token is None and self.process is None:
            callbacks=self._shutdown_acks;self._shutdown_acks=[]
            for finished in callbacks:finished()

    def closeEvent(self,event):
        self._closing=True;self.stop();super().closeEvent(event)
