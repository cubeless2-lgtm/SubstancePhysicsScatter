"""Designer-owned editor for local viewer simulation drafts.

Designer can import explicitly selected asset bundles; material editing uses the viewer.
All HTTP writes use the existing loopback session and draft revision contract.
"""
from __future__ import annotations
import copy,json,math,re,tempfile,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HEX32=re.compile(r'^[0-9a-f]{32}$')
_HEX64=re.compile(r'^[0-9a-f]{64}$')
ROLES=('base_color','roughness','metallic','normal')

def current_material_bindings(record):
    result={}
    for role in ROLES:
        value=record.get(role+'_texture')
        if not value:result[role]={'mode':'none'};continue
        setting=dict(mode='texture',texture_id=value['texture_id'],channel=value['channel'],color_space=value['color_space'],wrap=value['wrap_u'])
        if role=='normal':setting['normal_convention']=value['normal_convention']
        result[role]=setting
    return result

def material_edit_body(slot,bindings):
    if not re.fullmatch(r'0|[1-9][0-9]?',str(slot)) or int(slot)>63 or not bindings or not set(bindings)<=set(ROLES):raise ValueError('재질 슬롯 또는 역할이 올바르지 않습니다.')
    result={}
    for role,value in bindings.items():
        mode=value.get('mode')
        if mode in ('auto','none'):result[role]={'mode':mode};continue
        if mode!='texture' or not _HEX64.fullmatch(str(value.get('texture_id',''))):raise ValueError('텍스처를 선택하세요: '+role)
        channel=value.get('channel');space=value.get('color_space');wrap=value.get('wrap')
        if channel not in (('rgb',) if role in ('base_color','normal') else ('r','g','b')) or space not in (('sRGB','linear') if role=='base_color' else ('linear',)) or wrap not in ('repeat','clamp'):raise ValueError('텍스처 채널·색공간·wrap 설정이 올바르지 않습니다: '+role)
        result[role]=dict(mode='texture',texture_id=value['texture_id'],channel=channel,color_space=space,wrap=wrap)
        if role=='normal':
            if value.get('normal_convention') not in ('DirectX','OpenGL'):raise ValueError('노멀 방향을 선택하세요.')
            result[role]['normal_convention']=value['normal_convention']
    return {'bindings':{str(slot):result}}

def material_conflicts(originals,dirty_roles,latest_records):
    """Only overlapping remote edits conflict; never silently rebase them."""
    records={str(record['material_id']):current_material_bindings(record) for record in latest_records}
    conflicts={}
    for slot,roles in dirty_roles.items():
        before=originals.get(slot);after=records.get(slot)
        changed={role for role in roles if before is None or after is None or before.get(role)!=after.get(role)}
        if changed:conflicts[slot]=changed
    return conflicts

def close_upload_devices(devices,is_valid):
    """Close live Qt devices even when another device's C++ owner is gone."""
    errors=[]
    for device in devices:
        try:
            if is_valid(device):device.close()
        except (RuntimeError,ReferenceError,TypeError) as error:errors.append(str(error))
    return errors

def snapshot_asset_bundle(paths,directory,cancelled=None):
    """Copy explicitly selected files on a worker thread using bounded chunks."""
    if not 1<=len(paths)<=20:raise ValueError('OBJ 또는 FBX 한 개와 필요한 외부 파일을 최대 20개 선택하세요.')
    root=Path(directory);names=set();parents=set();total=0;meshes=0;out=[]
    for name in paths:
        if cancelled is not None and cancelled.is_set():raise InterruptedError('자산 복사가 취소됐습니다.')
        p=Path(name);filename=p.name;suffix=p.suffix.lower()
        if not filename or len(filename)>120 or any(c in '/\\:<>"|?*' or ord(c)<32 for c in filename) or filename.startswith('.') or filename.endswith(('.', ' ')) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',filename,re.I):raise ValueError('지원하지 않는 파일 이름: '+filename)
        if suffix not in ('.obj','.fbx','.mtl','.png','.jpg','.jpeg') or filename.casefold() in names:raise ValueError('지원하지 않는 형식 또는 중복 파일: '+filename)
        names.add(filename.casefold());parents.add(p.parent.resolve());meshes+=suffix in ('.obj','.fbx')
        before=p.stat()
        if not p.is_file() or before.st_size>32*1024*1024:raise ValueError('파일을 읽을 수 없거나 32 MiB를 초과합니다: '+filename)
        total+=before.st_size
        if total>128*1024*1024:raise ValueError('선택한 파일이 총 128 MiB를 초과합니다.')
        target=root/filename;copied=0
        with p.open('rb') as source,target.open('xb') as destination:
            while True:
                if cancelled is not None and cancelled.is_set():raise InterruptedError('자산 복사가 취소됐습니다.')
                block=source.read(1024*1024)
                if not block:break
                copied+=len(block)
                if copied>before.st_size:raise ValueError('읽는 동안 원본 파일이 변경됐습니다: '+filename)
                destination.write(block)
        after=p.stat()
        if copied!=before.st_size or before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns:raise ValueError('읽는 동안 원본 파일이 변경됐습니다: '+filename)
        out.append(target)
    if meshes!=1 or len(parents)!=1:raise ValueError('같은 폴더에서 OBJ 또는 FBX 한 개와 필요한 부속 파일을 선택하세요.')
    return out

def snapshot_texture_bundle(paths,directory,cancelled=None):
    if not 1<=len(paths)<=8:raise ValueError('PNG 또는 JPG 텍스처를 1~8개 선택하세요.')
    root=Path(directory);out=[];names=set();total=0
    for name in paths:
        if cancelled is not None and cancelled.is_set():raise InterruptedError('텍스처 복사가 취소됐습니다.')
        p=Path(name);filename=p.name
        if not filename or len(filename)>120 or p.suffix.lower() not in ('.png','.jpg','.jpeg') or filename.casefold() in names or any(c in '/\\:<>"|?*' or ord(c)<32 for c in filename) or filename.startswith('.') or filename.endswith(('.', ' ')) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',filename,re.I):raise ValueError('지원하지 않는 파일 또는 중복 이름: '+filename)
        names.add(filename.casefold());before=p.stat()
        if not p.is_file() or before.st_size>32*1024*1024:raise ValueError('파일을 읽을 수 없거나 32 MiB를 초과합니다: '+filename)
        total+=before.st_size
        if total>128*1024*1024:raise ValueError('선택한 파일이 총 128 MiB를 초과합니다.')
        target=root/filename;copied=0
        with p.open('rb') as source,target.open('xb') as destination:
            while True:
                if cancelled is not None and cancelled.is_set():raise InterruptedError('텍스처 복사가 취소됐습니다.')
                block=source.read(1024*1024)
                if not block:break
                copied+=len(block)
                if copied>before.st_size:raise ValueError('읽는 동안 원본 파일이 변경됐습니다: '+filename)
                destination.write(block)
        after=p.stat()
        if copied!=before.st_size or before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns:raise ValueError('읽는 동안 원본 파일이 변경됐습니다: '+filename)
        out.append(target)
    return out

def asset_revisions(rows):
    result={}
    for row in rows:
        key=row.get('asset_id');metadata=row.get('metadata') or {};files=metadata.get('files') or {}
        if type(key) is not str or not _HEX32.fullmatch(key) or key in result or not row.get('enabled'):
            raise ValueError('선택한 자산이 없거나 중복됐습니다. 새로고침하세요.')
        result[key]=dict(render_revision=row.get('render_revision'),material_revision=row.get('material_revision'),physics_sha256=files.get('physics.obj'))
    return result

def build_draft(rows, simulation, bake):
    if not 1<=len(rows)<=6:raise ValueError('자산을 1~6개 선택하세요.')
    revisions=asset_revisions(rows);choices=[]
    for row in rows:
        scale,weight=row['choice_scale'],row['choice_weight']
        if not all(type(x) in (int,float) and math.isfinite(x) for x in (scale,weight)) or not 0<scale<=100 or not 0<=weight<=1000000:raise ValueError('자산 크기 또는 가중치 범위가 올바르지 않습니다.')
        choices.append(dict(asset_id=row['asset_id'],scale=float(scale),weight=float(weight)))
    if not any(row['weight']>0 for row in choices):raise ValueError('양수 가중치가 하나 이상 필요합니다.')
    return dict(assets=choices,simulation=copy.deepcopy(simulation),bake=copy.deepcopy(bake),mask_id=None),revisions

def verify_receipt(receipt,expected_revisions,expected_current,expected_settings=None):
    if type(receipt) is not dict or type(receipt.get('revision')) is not str or not _HEX32.fullmatch(receipt['revision']):raise ValueError('뷰어 설정 응답이 올바르지 않습니다.')
    if receipt.get('asset_revisions')!=expected_revisions or receipt.get('current_job_id')!=expected_current:
        raise ValueError('전송 중 자산 또는 현재 결과가 변경됐습니다. 새로고침한 뒤 다시 보내세요.')
    if expected_settings is not None and receipt.get('settings')!=expected_settings:raise ValueError('전송된 설정이 응답과 다릅니다. 다시 보내세요.')
    return receipt['revision']

def open_viewer_settings(panel, *, expected_root=None):
    """Open one nonmodal editor owned by Panel; returns the Qt dialog."""
    from PySide6 import QtCore,QtGui,QtNetwork,QtWidgets
    import shiboken6
    from . import viewer_runtime
    trusted_root=Path(expected_root).resolve() if expected_root is not None else viewer_runtime.checkout_root()
    existing=getattr(panel,'_viewer_settings_dialog',None)
    if existing is not None:
        try:existing.show();existing.raise_();existing.activateWindow();return existing
        except RuntimeError:panel._viewer_settings_dialog=None

    class Dialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(panel);self.setWindowTitle('Viewer 자산 · 시뮬레이션 설정');self.resize(740,720)
            self.network=QtNetwork.QNetworkAccessManager(self);self.reply=None;self.session=None;self.ready=False;self.rows=[];self.current=None;self.revision=None
            self.shutting_down=False;self.shutdown_callbacks=[];self.closing_for_shutdown=False
            self.material_drafts={};self.material_dirty=set();self.material_dirty_roles={};self.material_originals={};self.material_conflict_assets=set();self.material_bases={};self.material_asset=None;self.material_slot_id=None;self.material_loading=False
            self.preview_serial=0;self.preview_replies=[]
            self.upload_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='scatter-import');self.upload_future=None;self.upload_temp=None;self.upload_devices=[];self.upload_timer=QtCore.QTimer(self);self.upload_timer.setInterval(50);self.upload_timer.timeout.connect(self.snapshot_ready)
            self.upload_cancel=threading.Event()
            outer=QtWidgets.QVBoxLayout(self);note=QtWidgets.QLabel('OBJ/FBX와 필요한 MTL·텍스처를 같은 폴더에서 함께 선택하세요. 자산을 선택해 재질 슬롯과 텍스처를 편집할 수 있습니다. Graph 마스크는 제출 후 Designer에서 선택·Inspect합니다.');note.setWordWrap(True);outer.addWidget(note)
            self.controls=QtWidgets.QWidget();outer.addWidget(self.controls);layout=QtWidgets.QVBoxLayout(self.controls)
            imports=QtWidgets.QHBoxLayout();layout.addLayout(imports)
            self.import_units=QtWidgets.QComboBox();[self.import_units.addItem(label,value) for label,value in [('m','m'),('cm','cm'),('mm','mm')]];imports.addWidget(self.import_units)
            self.import_axis=QtWidgets.QComboBox();self.import_axis.addItems(['Z','Y']);imports.addWidget(self.import_axis)
            self.import_forward=QtWidgets.QComboBox();self.import_forward.addItems(['Y','-Z','X','-X','Z','-Y']);imports.addWidget(self.import_forward)
            self.import_mode=QtWidgets.QComboBox();self.import_mode.addItem('FBX 단위 자동','auto');self.import_mode.addItem('단위·축 직접 지정','override');imports.addWidget(self.import_mode)
            self.import_parts=QtWidgets.QComboBox();self.import_parts.addItem('하나로 묶기','group');self.import_parts.addItem('메시별 분리','split');imports.addWidget(self.import_parts)
            self.add_asset=QtWidgets.QPushButton('OBJ/FBX와 부속 파일 추가');self.add_asset.clicked.connect(self.choose_assets);layout.addWidget(self.add_asset)
            self.table=QtWidgets.QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['사용','자산','크기','가중치']);self.table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeMode.Stretch);layout.addWidget(self.table)
            self.table.currentCellChanged.connect(self.show_material)
            self.material_status=QtWidgets.QLabel('자산을 선택하면 원본 재질 연결 상태를 표시합니다.');self.material_status.setTextFormat(QtCore.Qt.TextFormat.PlainText);self.material_status.setWordWrap(True);layout.addWidget(self.material_status)
            self.material_group=QtWidgets.QGroupBox('재질 슬롯 · 텍스처 연결');layout.addWidget(self.material_group);material_layout=QtWidgets.QVBoxLayout(self.material_group)
            self.material_slot=QtWidgets.QComboBox();self.material_slot.currentIndexChanged.connect(self.material_slot_changed);material_layout.addWidget(self.material_slot)
            grid=QtWidgets.QGridLayout();material_layout.addLayout(grid)
            for column,label in enumerate(('역할','텍스처','채널','색공간','UV wrap','Normal 방향','원본 미리보기')):grid.addWidget(QtWidgets.QLabel(label),0,column)
            self.material_fields={}
            for row,(role,label) in enumerate((('base_color','Base Color'),('roughness','Roughness'),('metallic','Metallic'),('normal','Normal')),1):
                grid.addWidget(QtWidgets.QLabel(label),row,0);widgets={}
                for column,key in enumerate(('texture','channel','color_space','wrap','normal_convention'),1):
                    box=QtWidgets.QComboBox();grid.addWidget(box,row,column);widgets[key]=box;box.currentIndexChanged.connect(lambda _index,selected_role=role:self.material_changed(selected_role))
                preview=QtWidgets.QLabel('없음');preview.setFixedSize(64,64);preview.setScaledContents(True);grid.addWidget(preview,row,6);widgets['preview']=preview
                self.material_fields[role]=widgets
            material_buttons=QtWidgets.QHBoxLayout();material_layout.addLayout(material_buttons)
            self.material_apply=QtWidgets.QPushButton('현재 슬롯 재질 연결 적용');self.material_apply.clicked.connect(self.apply_material);material_buttons.addWidget(self.material_apply)
            self.material_refresh=QtWidgets.QPushButton('서버 최신 자산 확인');self.material_refresh.clicked.connect(self.refresh_material);material_buttons.addWidget(self.material_refresh)
            self.material_discard=QtWidgets.QPushButton('현재 슬롯 편집 취소');self.material_discard.clicked.connect(self.discard_material);material_buttons.addWidget(self.material_discard)
            self.texture_upload=QtWidgets.QPushButton('512 텍스처 추가');self.texture_upload.clicked.connect(self.choose_textures);material_buttons.addWidget(self.texture_upload)
            self.material_group.setEnabled(False)
            scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);body=QtWidgets.QWidget();form=QtWidgets.QFormLayout(body);scroll.setWidget(body);layout.addWidget(scroll)
            self.fields={}
            def number(name,label,lo,hi,default,integer=False,step=None):
                box=QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox();box.setRange(lo,hi);box.setValue(default)
                if not integer:box.setDecimals(4)
                if step is not None:box.setSingleStep(step)
                self.fields[name]=box;form.addRow(label,box)
            number('count','물체 개수',1,5000,40,True);number('seed','Seed',0,4294967295,1)
            self.fields['seed'].setDecimals(0)
            number('width','영역 너비 (m)',.1,1000,4);number('depth','영역 깊이 (m)',.1,1000,4);number('seconds','시뮬레이션 시간 (초)',.1,120,12)
            number('friction','마찰',0,2,.6,step=.05);number('restitution','반발',0,1,.05,step=.05)
            self.fields['placement_jitter']=QtWidgets.QCheckBox('초기 위치·높이 분산');form.addRow(self.fields['placement_jitter'])
            self.fields['edges']=QtWidgets.QComboBox();self.fields['edges'].addItem('벽','walls');self.fields['edges'].addItem('열린 영역','open');self.fields['edges'].addItem('주기 경계','periodic');form.addRow('경계',self.fields['edges'])
            self.fields['resolution']=QtWidgets.QComboBox()
            for v in (64,128,256,512,1024,2048):self.fields['resolution'].addItem(str(v),v)
            self.fields['resolution'].setCurrentIndex(3);form.addRow('베이크 해상도',self.fields['resolution'])
            number('height_min','최소 높이 (m)',-1000,1000,0);number('height_max','최대 높이 (m)',-1000,1000,2)
            self.fields['normal']=QtWidgets.QComboBox();self.fields['normal'].addItems(['OpenGL','DirectX']);form.addRow('노멀 형식',self.fields['normal'])
            self.fields['samples']=QtWidgets.QComboBox()
            for v in (1,2,3,4):self.fields['samples'].addItem(str(v),v)
            form.addRow('샘플 / 축',self.fields['samples'])
            buttons=QtWidgets.QHBoxLayout();self.refresh=QtWidgets.QPushButton('뷰어 자산 새로고침');self.refresh.clicked.connect(self.load);buttons.addWidget(self.refresh);self.submit=QtWidgets.QPushButton('Designer 계산 설정 제출');self.submit.clicked.connect(self.send);buttons.addWidget(self.submit);self.open=QtWidgets.QPushButton('3D 뷰어에서 재질·텍스처 수정');self.open.clicked.connect(panel.open_local_viewer);buttons.addWidget(self.open);outer.addLayout(buttons)
            self.status=QtWidgets.QLabel('뷰어 연결 중…');self.status.setWordWrap(True);outer.addWidget(self.status);self.submit.setEnabled(False);self.load()
        def closeEvent(self,event):
            if self.reply is not None or self.upload_future is not None:self.status.setText('가져오기 또는 요청이 끝난 뒤 창을 닫아 주세요.');event.ignore();return
            if self.shutting_down and not self.closing_for_shutdown:
                event.ignore();QtCore.QTimer.singleShot(0,self.finish_shutdown);return
            if self.upload_temp is not None:
                warning=self.cleanup_upload()
                if self.upload_temp is not None:self.status.setText('임시 파일을 정리하지 못해 창을 닫을 수 없습니다: '+warning);event.ignore();return
            self.stop_previews();self.upload_pool.shutdown(wait=False,cancel_futures=True)
            panel._viewer_settings_dialog=None;super().closeEvent(event)
        def request_shutdown(self,callback):
            self.shutting_down=True;self.upload_cancel.set();self.stop_previews();self.shutdown_callbacks.append(callback);self.controls.setEnabled(False);self.submit.setEnabled(False);self.refresh.setEnabled(False);self.open.setEnabled(False)
            self.finish_shutdown()
        def finish_shutdown(self):
            if not self.shutting_down or self.reply is not None or self.upload_future is not None:return
            if self.upload_temp is not None:
                warning=self.cleanup_upload()
                if self.upload_temp is not None:panel.message('임시 파일을 정리하지 못해 종료가 보류됩니다: '+warning);return
            callbacks=self.shutdown_callbacks
            try:
                self.closing_for_shutdown=True
                if not self.close():panel.message('설정 창을 안전하게 닫지 못했습니다. 종료가 보류됩니다.');return
            except RuntimeError as error:
                panel.message('설정 창 종료 실패: '+str(error));return
            finally:self.closing_for_shutdown=False
            self.shutdown_callbacks=[]
            for callback in callbacks:callback()
        def request(self,method,path,payload,callback,*,asset_revision=None,material_operation=False):
            if self.shutting_down:raise ValueError('Designer 플러그인을 종료하고 있습니다.')
            if self.reply is not None:raise ValueError('이전 요청이 진행 중입니다.')
            req=QtNetwork.QNetworkRequest(QtCore.QUrl(panel.local_viewer_url()+path));req.setTransferTimeout(150000 if path=='api/assets' or path.endswith('/textures') else 12000)
            if self.session:req.setRawHeader(b'X-Review-Token',self.session.encode('ascii'))
            if asset_revision is not None:req.setRawHeader(b'X-Asset-Revision',asset_revision.encode('ascii'))
            if isinstance(payload,QtNetwork.QHttpMultiPart):
                reply=self.network.post(req,payload);payload.setParent(reply)
            elif payload is None:reply=self.network.get(req)
            else:
                req.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
                body=QtCore.QByteArray(json.dumps(payload,allow_nan=False,separators=(',',':')).encode())
                reply=self.network.post(req,body) if method=='POST' else self.network.sendCustomRequest(req,b'DELETE',body)
            self.reply=reply;self.controls.setEnabled(False);self.submit.setEnabled(False);self.refresh.setEnabled(False);buffer=bytearray();oversized=[False]
            def ready():
                buffer.extend(bytes(reply.readAll()))
                if len(buffer)>2*1024*1024 and not oversized[0]:oversized[0]=True;reply.abort()
            def finished():
                try:
                    ready()
                    if oversized[0]:raise ValueError('뷰어 응답 크기가 제한을 초과했습니다.')
                    if reply.error()!=QtNetwork.QNetworkReply.NetworkError.NoError:
                        try:detail=json.loads(bytes(buffer)).get('detail')
                        except (ValueError,TypeError,AttributeError):detail=None
                        raise ValueError('뷰어 요청 실패: '+str(detail or reply.errorString()))
                    value=json.loads(bytes(buffer));self.reply=None
                    if not (self.shutting_down and method=='GET'):callback(value)
                except Exception as error:
                    if not material_operation:self.ready=False
                    suffix=' · 새로고침 후 다시 확인하세요.'
                    if method=='POST' and path=='api/assets':suffix=' · 가져오기 결과가 불명확합니다. 뷰어에 이미 추가됐는지 확인한 뒤 재시도하세요.'
                    if material_operation:suffix=' · 편집값은 유지됩니다. 서버 최신 자산을 확인한 뒤 다시 적용하세요.'
                    if method=='POST' and path.endswith('/textures'):suffix=' · 업로드 결과가 불명확합니다. 서버 최신 자산을 확인한 뒤 재시도하세요. 편집값은 유지됩니다.'
                    self.status.setText(str(error)+suffix);self.reply=None
                    if self.shutting_down:panel.message(self.status.text())
                finally:
                    if self.reply is None:
                        warning=self.cleanup_upload()
                        if warning:
                            self.status.setText(self.status.text()+' · 임시 파일 정리 실패: '+warning)
                            if self.shutting_down:panel.message(self.status.text())
                        if not self.shutting_down:self.controls.setEnabled(True);self.submit.setEnabled(bool(self.session) and self.ready);self.add_asset.setEnabled(bool(self.session) and self.ready);self.refresh.setEnabled(True)
                    reply.deleteLater()
                    self.finish_shutdown()
            reply.readyRead.connect(ready);reply.finished.connect(finished)
        def load(self):
            try:
                if self.material_dirty:raise ValueError('미적용 재질 편집이 있습니다. 적용하거나 해당 슬롯 편집을 취소한 뒤 전체 자산을 새로고침하세요. 입력은 보존됩니다.')
                self.session=None;self.ready=False;self.status.setText('뷰어 연결을 확인하는 중…');self.request('GET','api/viewer-health',None,self.health_loaded)
            except Exception as error:self.status.setText(str(error))
        def health_loaded(self,health):
            viewer_runtime.validate_health(health,trusted_root)
            self.request('GET','api/state',None,self.loaded)
        def set_asset_row(self,index,row,choice=None):
            ident=row['asset_id'];check=QtWidgets.QCheckBox();check.setChecked(bool(choice));self.table.setCellWidget(index,0,check)
            text=QtWidgets.QTableWidgetItem(str(row.get('name',ident)));text.setFlags(text.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable);self.table.setItem(index,1,text)
            for col,key in ((2,'scale'),(3,'weight')):
                spin=QtWidgets.QDoubleSpinBox();spin.setDecimals(4);spin.setRange(.0001 if key=='scale' else 0,100 if key=='scale' else 1000000);spin.setValue(float((choice or row).get(key,1)));self.table.setCellWidget(index,col,spin)
        def show_material(self,index,*_):
            if not 0<=index<len(self.rows):self.stop_previews();self.material_status.setText('자산을 선택하면 원본 재질 연결 상태를 표시합니다.');self.material_asset=None;self.material_group.setEnabled(False);return
            asset=self.rows[index];metadata=asset.get('metadata') or {};lines=[str(asset.get('name','자산'))+' · '+('재질 준비됨' if metadata.get('material_ready') else '재질 입력 확인 필요')]
            texture_names={x.get('texture_id'):x.get('source_name') for x in asset.get('texture_options') or []}
            for material in metadata.get('materials') or []:
                roles=material.get('roles') or {};parts=[]
                for key,label in (('base_color','Base Color'),('roughness','Roughness'),('metallic','Metallic'),('normal','Normal')):
                    value=roles.get(key) or {};binding=value.get('binding') or {}
                    name=texture_names.get(binding.get('texture_id')) or binding.get('source_name') or binding.get('texture_id') or value.get('status') or '없음'
                    details=[str(binding[k]) for k in ('channel','color_space','normal_convention') if binding.get(k)]
                    parts.append(label+': '+str(name)+(' ('+', '.join(details)+')' if details else ''))
                lines.append(str(material.get('name','재질'))+' · '+', '.join(parts))
            for warning in (metadata.get('warnings') or [])[:5]:lines.append('안내: '+str(warning))
            lines.append('재질 연결을 수정해도 기존 배치와 베이크는 유지됩니다. 최신 재질의 베이크가 필요하면 재베이크하세요.')
            self.material_status.setText('\n'.join(lines))
            records=metadata.get('material_records') or [];self.material_asset=asset['asset_id']
            if not any(key[0]==self.material_asset for key in self.material_dirty):
                if self.material_bases.get(self.material_asset)!=asset.get('asset_revision'):
                    for key in list(self.material_drafts):
                        if key[0]==self.material_asset:self.material_drafts.pop(key);self.material_originals.pop(key,None);self.material_dirty_roles.pop(key,None)
                self.material_bases[self.material_asset]=asset.get('asset_revision')
            self.material_group.setEnabled(bool(metadata.get('material_ready') and records))
            self.material_loading=True;self.material_slot.clear()
            for record in records:self.material_slot.addItem('Material slot '+str(record['material_id']),str(record['material_id']))
            self.material_loading=False;self.material_slot_changed()
        def material_slot_changed(self,*_):
            if self.material_loading or not self.material_asset:return
            slot=self.material_slot.currentData();asset=next((row for row in self.rows if row['asset_id']==self.material_asset),None)
            if slot is None or asset is None:return
            record=next((x for x in asset['metadata'].get('material_records',[]) if str(x['material_id'])==slot),None)
            if record is None:return
            self.material_slot_id=slot;key=(self.material_asset,slot)
            original=current_material_bindings(record);self.material_originals.setdefault(key,copy.deepcopy(original))
            values=self.material_drafts.setdefault(key,original);options=asset.get('texture_options') or []
            self.material_loading=True
            try:
                for role,widgets in self.material_fields.items():
                    value=values[role];texture=widgets['texture'];texture.clear();texture.addItem('원본 자동','auto');texture.addItem('없음','none')
                    for option in options:texture.addItem(str(option.get('source_name') or option.get('texture_id')),option.get('texture_id'))
                    selected=value.get('texture_id') if value.get('mode')=='texture' else value.get('mode','none')
                    if texture.findData(selected)<0:texture.addItem('누락된 텍스처: '+str(selected),'missing:'+str(selected));selected='missing:'+str(selected)
                    texture.setCurrentIndex(texture.findData(selected))
                    for field,choices,default in (('channel',[('RGB','rgb')] if role in ('base_color','normal') else [('R','r'),('G','g'),('B','b')],'rgb' if role in ('base_color','normal') else 'r'),('color_space',[('sRGB','sRGB'),('Linear','linear')] if role=='base_color' else [('Linear / Non-Color','linear')],'sRGB' if role=='base_color' else 'linear'),('wrap',[('Repeat','repeat'),('Clamp','clamp')],'repeat'),('normal_convention',[('OpenGL +Y','OpenGL'),('DirectX -Y','DirectX')],'OpenGL')):
                        box=widgets[field];box.clear()
                        for label,data in choices:box.addItem(label,data)
                        selected_value=value.get(field,default);position=box.findData(selected_value);box.setCurrentIndex(max(0,position));box.setEnabled(value.get('mode')=='texture' and (field!='normal_convention' or role=='normal'))
            finally:self.material_loading=False
            self.material_apply.setEnabled(True);self.update_previews()
        def material_changed(self,changed_role):
            if self.material_loading or not self.material_asset or self.material_slot_id is None:return
            values={}
            for role,widgets in self.material_fields.items():
                selected=widgets['texture'].currentData()
                if selected in ('auto','none'):values[role]={'mode':selected}
                else:
                    values[role]=dict(mode='texture',texture_id=selected,channel=widgets['channel'].currentData(),color_space=widgets['color_space'].currentData(),wrap=widgets['wrap'].currentData())
                    if role=='normal':values[role]['normal_convention']=widgets['normal_convention'].currentData()
                for field in ('channel','color_space','wrap','normal_convention'):widgets[field].setEnabled(selected not in ('auto','none') and (field!='normal_convention' or role=='normal'))
            key=(self.material_asset,self.material_slot_id);self.material_drafts[key]=values
            dirty=self.material_dirty_roles.setdefault(key,set())
            if values[changed_role]==self.material_originals[key][changed_role]:dirty.discard(changed_role)
            else:dirty.add(changed_role)
            if dirty:self.material_dirty.add(key)
            else:self.material_dirty.discard(key)
            self.update_previews()
        def stop_previews(self):
            self.preview_serial+=1;replies=self.preview_replies;self.preview_replies=[]
            for reply in replies:
                try:
                    if shiboken6.isValid(reply):reply.abort()
                except RuntimeError:pass
        def update_previews(self):
            self.stop_previews()
            if self.shutting_down or not self.material_asset or self.material_slot_id is None:return
            serial=self.preview_serial;asset_id=self.material_asset
            asset=next((r for r in self.rows if r['asset_id']==asset_id),None)
            if asset is None:return
            values=self.material_drafts.get((asset_id,self.material_slot_id),{})
            source=(asset.get('material_source_bindings') or {}).get(str(self.material_slot_id))
            if source is None:
                record=next((r for r in asset['metadata'].get('material_records',[]) if str(r['material_id'])==str(self.material_slot_id)),{})
                source={role+'_texture':record.get(role+'_texture') for role in ROLES}
            for role,widgets in self.material_fields.items():
                label=widgets['preview'];label.clear();value=values.get(role) or {};binding=source.get(role+'_texture') if value.get('mode')=='auto' else value
                texture_id=(binding or {}).get('texture_id');channel=(binding or {}).get('channel','rgb')
                if type(texture_id) is not str or not _HEX64.fullmatch(texture_id) or channel not in ('rgb','r','g','b'):label.setText('없음');continue
                request=QtNetwork.QNetworkRequest(QtCore.QUrl(panel.local_viewer_url()+'api/assets/'+asset_id+'/textures/'+texture_id+'?channel='+channel));request.setTransferTimeout(10000)
                reply=self.network.get(request);self.preview_replies.append(reply);buffer=bytearray();oversized=[False]
                def ready(reply=reply,buffer=buffer,oversized=oversized):
                    if not shiboken6.isValid(reply):return
                    buffer.extend(bytes(reply.readAll()))
                    if len(buffer)>2*1024*1024 and not oversized[0]:oversized[0]=True;reply.abort()
                def finished(reply=reply,buffer=buffer,oversized=oversized,label=label,ready=ready):
                    try:
                        ready()
                        if not shiboken6.isValid(self) or not shiboken6.isValid(label) or self.shutting_down or serial!=self.preview_serial:return
                        image=QtGui.QPixmap()
                        if oversized[0] or not shiboken6.isValid(reply) or reply.error()!=QtNetwork.QNetworkReply.NetworkError.NoError or not image.loadFromData(bytes(buffer)):label.setText('미리보기 없음')
                        else:label.setPixmap(image)
                    finally:
                        if shiboken6.isValid(self) and reply in self.preview_replies:self.preview_replies.remove(reply)
                        if shiboken6.isValid(reply):reply.deleteLater()
                reply.readyRead.connect(ready);reply.finished.connect(finished)
        def apply_material(self):
            try:
                if not self.material_asset or self.material_slot_id is None:raise ValueError('재질 슬롯을 선택하세요.')
                if getattr(panel,'_token',None) is not None:raise ValueError('Designer 패널의 현재 작업이 끝난 뒤 적용하세요.')
                asset_id=self.material_asset;slot=self.material_slot_id;key=(asset_id,slot);revision=self.material_bases.get(asset_id)
                if type(revision) is not str or not _HEX64.fullmatch(revision):raise ValueError('자산 버전을 확인할 수 없습니다. 서버 최신 자산을 확인하세요.')
                if asset_id in self.material_conflict_assets:raise ValueError('동일 역할이 다른 창에서 변경됐습니다. 현재 슬롯 편집을 취소하거나 충돌을 해결하세요.')
                roles=self.material_dirty_roles.get(key) or set()
                if not roles:raise ValueError('변경된 재질 연결이 없습니다.')
                body=material_edit_body(slot,{role:self.material_drafts[key][role] for role in roles});self.status.setText('재질 연결을 적용하는 중… 기존 배치와 베이크는 유지됩니다.')
                def applied(value):
                    self.update_material_asset(asset_id,value);self.material_drafts.pop(key,None);self.material_originals.pop(key,None);self.material_dirty_roles.pop(key,None);self.material_dirty.discard(key)
                    if self.material_asset==asset_id:self.material_slot_changed()
                    self.status.setText('재질 연결 적용 완료 · 기존 배치와 베이크는 이전 결과입니다. 필요하면 재베이크하세요.')
                def health_ready(health):
                    viewer_runtime.validate_health(health,trusted_root)
                    self.request('POST','api/assets/'+asset_id+'/material',body,applied,asset_revision=revision,material_operation=True)
                self.request('GET','api/viewer-health',None,health_ready,material_operation=True)
            except Exception as error:self.status.setText(str(error))
        def update_material_asset(self,asset_id,value):
            if not isinstance(value,dict) or value.get('asset_id')!=asset_id or not _HEX64.fullmatch(str(value.get('asset_revision',''))):raise ValueError('자산 응답이 올바르지 않습니다. 서버 최신 자산을 확인하세요.')
            index=next((i for i,row in enumerate(self.rows) if row['asset_id']==asset_id),None)
            if index is None:raise ValueError('편집한 자산이 현재 목록에 없습니다.')
            self.rows[index]=value;self.material_bases[asset_id]=value['asset_revision']
        def refresh_material(self):
            try:
                asset_id=self.material_asset
                if not asset_id:raise ValueError('자산을 선택하세요.')
                def refreshed(state):
                    session=state.get('session_token') if isinstance(state,dict) else None
                    if type(session) is not str or not re.fullmatch(r'[0-9a-f]{64}',session):raise ValueError('뷰어 연결 응답이 올바르지 않습니다.')
                    row=next((a for a in state.get('assets',[]) if a.get('asset_id')==asset_id and a.get('enabled')),None)
                    if row is None:raise ValueError('자산이 삭제되었거나 비활성화됐습니다. 편집값은 보존됩니다.')
                    self.session=session
                    dirty={slot:roles for (aid,slot),roles in self.material_dirty_roles.items() if aid==asset_id and roles}
                    originals={slot:self.material_originals.get((asset_id,slot)) for slot in dirty}
                    conflicts=material_conflicts(originals,dirty,(row.get('metadata') or {}).get('material_records') or [])
                    if conflicts:
                        index=next(i for i,a in enumerate(self.rows) if a['asset_id']==asset_id);self.rows[index]=row;self.material_conflict_assets.add(asset_id)
                        if self.material_asset==asset_id:self.show_material(index)
                        self.status.setText('같은 재질 역할이 다른 창에서 변경됐습니다: '+str({k:sorted(v) for k,v in conflicts.items()})+' · 입력은 보존됩니다. 현재 슬롯 편집을 취소하고 다시 확인하세요.')
                        return
                    records={str(record['material_id']):current_material_bindings(record) for record in (row.get('metadata') or {}).get('material_records') or []}
                    for key,draft in self.material_drafts.items():
                        if key[0]!=asset_id or key[1] not in records:continue
                        roles=self.material_dirty_roles.get(key) or set();original=self.material_originals[key]
                        for role in ROLES:
                            if role not in roles:draft[role]=copy.deepcopy(records[key[1]][role]);original[role]=copy.deepcopy(records[key[1]][role])
                    self.material_conflict_assets.discard(asset_id);self.update_material_asset(asset_id,row)
                    if self.material_asset==asset_id:self.show_material(next(i for i,a in enumerate(self.rows) if a['asset_id']==asset_id))
                    self.status.setText('최신 자산 확인 완료 · 입력한 재질 설정을 검토한 뒤 다시 적용하세요.')
                def health_ready(health):viewer_runtime.validate_health(health,trusted_root);self.request('GET','api/state',None,refreshed,material_operation=True)
                self.request('GET','api/viewer-health',None,health_ready,material_operation=True)
            except Exception as error:self.status.setText(str(error))
        def discard_material(self):
            if not self.material_asset or self.material_slot_id is None:return
            key=(self.material_asset,self.material_slot_id);self.material_drafts.pop(key,None);self.material_originals.pop(key,None);self.material_dirty_roles.pop(key,None);self.material_dirty.discard(key)
            if not any(k[0]==self.material_asset for k in self.material_dirty):self.material_conflict_assets.discard(self.material_asset)
            self.material_slot_changed();self.status.setText('현재 슬롯의 미적용 재질 편집을 취소했습니다. 최신 서버 자산을 확인한 뒤 적용하세요.')
        def choose_textures(self):
            names,_=QtWidgets.QFileDialog.getOpenFileNames(self,'512×512 PNG/JPG 텍스처 선택','','이미지 (*.png *.jpg *.jpeg)')
            if names:self.upload_textures(names)
        def upload_textures(self,names):
            try:
                if self.shutting_down or getattr(panel,'_token',None) is not None:raise ValueError('현재 Designer 작업이 끝난 뒤 추가하세요.')
                if self.reply is not None or self.upload_future is not None:raise ValueError('다른 요청이 이미 진행 중입니다.')
                asset_id=self.material_asset;revision=self.material_bases.get(asset_id)
                if not asset_id or type(revision) is not str or not _HEX64.fullmatch(revision):raise ValueError('자산과 버전을 먼저 확인하세요.')
                self.upload_kind='textures';self.upload_asset_id=asset_id;self.upload_revision=revision;self.upload_options={}
                self.upload_temp=tempfile.TemporaryDirectory(prefix='scatter-texture-');self.upload_cancel.clear()
                self.upload_future=self.upload_pool.submit(snapshot_texture_bundle,list(names),self.upload_temp.name,self.upload_cancel)
                self.controls.setEnabled(False);self.submit.setEnabled(False);self.refresh.setEnabled(False)
                self.status.setText('텍스처를 백그라운드에서 임시 복사 중… 원본은 변경하지 않습니다.');self.upload_timer.start()
            except Exception as error:
                if self.upload_future is None:self.cleanup_upload()
                self.status.setText(str(error))
        def textures_uploaded(self,value):
            asset_id=self.upload_asset_id;self.update_material_asset(asset_id,value)
            if self.material_asset==asset_id:self.material_slot_changed()
            self.status.setText('텍스처 추가 완료 · 기존 입력을 보존했습니다. 슬롯을 확인하고 연결을 적용하세요.')
        def choose_assets(self):
            names,_=QtWidgets.QFileDialog.getOpenFileNames(self,'OBJ/FBX와 필요한 부속 파일 선택','','지원 파일 (*.obj *.fbx *.mtl *.png *.jpg *.jpeg)')
            if names:self.upload_assets(names)
        def upload_assets(self,names):
            try:
                if self.shutting_down:raise ValueError('Designer 플러그인을 종료하고 있습니다.')
                if getattr(panel,'_token',None) is not None:raise ValueError('Designer 패널의 현재 작업이 끝난 뒤 추가하세요.')
                if self.reply is not None or self.upload_future is not None:raise ValueError('가져오기 또는 요청이 이미 진행 중입니다.')
                self.upload_kind='asset';self.upload_options=dict(units=self.import_units.currentText(),up_axis=self.import_axis.currentText(),forward_axis=self.import_forward.currentText(),import_mode=self.import_mode.currentData(),parts_mode=self.import_parts.currentData())
                self.upload_temp=tempfile.TemporaryDirectory(prefix='scatter-import-')
                self.upload_cancel.clear();self.upload_future=self.upload_pool.submit(snapshot_asset_bundle,list(names),self.upload_temp.name,self.upload_cancel)
                self.controls.setEnabled(False);self.submit.setEnabled(False);self.refresh.setEnabled(False)
                self.status.setText('원본을 백그라운드에서 임시 복사 중… 원본은 변경하지 않습니다.');self.upload_timer.start()
            except Exception as error:
                if self.upload_future is None:self.cleanup_upload()
                self.status.setText(str(error))
        def close_devices(self):
            errors=close_upload_devices(self.upload_devices,shiboken6.isValid);self.upload_devices=[]
            return '; '.join(errors)
        def cleanup_upload(self):
            warning=self.close_devices()
            if self.upload_temp is not None:
                temporary=self.upload_temp
                try:temporary.cleanup();self.upload_temp=None
                except OSError as error:warning+=' '+str(error)
            return warning.strip()
        def snapshot_ready(self):
            if self.upload_future is None or not self.upload_future.done():return
            self.upload_timer.stop();future=self.upload_future;self.upload_future=None
            try:
                files=future.result();options=self.upload_options
                if self.shutting_down:
                    warning=self.cleanup_upload()
                    if warning:panel.message('임시 파일 정리 실패: '+warning)
                    self.finish_shutdown();return
                self.status.setText('선택한 자산을 뷰어로 가져오는 중…')
                def health_ready(health):
                    viewer_runtime.validate_health(health,trusted_root)
                    multi=QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.ContentType.FormDataType)
                    for path in files:
                        device=QtCore.QFile(str(path));device.setParent(multi)
                        if not device.open(QtCore.QIODevice.OpenModeFlag.ReadOnly):raise ValueError('임시 자산을 열 수 없습니다: '+path.name)
                        self.upload_devices.append(device)
                        part=QtNetwork.QHttpPart();part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentDispositionHeader,'form-data; name="files"; filename="'+path.name+'"');part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/octet-stream');part.setBodyDevice(device);multi.append(part)
                    for name,value in options.items():
                        part=QtNetwork.QHttpPart();part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentDispositionHeader,'form-data; name="'+name+'"');part.setBody(QtCore.QByteArray(value.encode('utf8')));multi.append(part)
                    if self.upload_kind=='textures':self.request('POST','api/assets/'+self.upload_asset_id+'/textures',multi,self.textures_uploaded,asset_revision=self.upload_revision,material_operation=True)
                    else:self.request('POST','api/assets',multi,self.assets_uploaded)
                self.request('GET','api/viewer-health',None,health_ready,material_operation=self.upload_kind=='textures')
            except Exception as error:
                warning=self.cleanup_upload()
                if not self.shutting_down:self.controls.setEnabled(True);self.refresh.setEnabled(True);self.submit.setEnabled(bool(self.session) and self.ready);self.status.setText(str(error)+(' · '+warning if warning else ''))
                self.finish_shutdown()
        def assets_uploaded(self,response):
            items=response.get('assets') if isinstance(response,dict) and 'assets' in response else [response]
            if type(items) is not list or not items:raise ValueError('가져온 자산 응답이 올바르지 않습니다. 새로고침하세요.')
            asset_revisions(items);existing={row['asset_id'] for row in self.rows}
            if any(row['asset_id'] in existing for row in items):raise ValueError('가져온 자산 ID가 중복됐습니다. 새로고침하세요.')
            first=len(self.rows);self.rows.extend(items);self.table.setRowCount(len(self.rows))
            for index in range(first,len(self.rows)):self.set_asset_row(index,self.rows[index])
            self.table.setCurrentCell(first,1);self.show_material(first)
            self.status.setText('자산 '+str(len(items))+'개를 추가했습니다. 계산에 쓸 항목을 선택하세요. 기존 설정과 결과는 보존했습니다.')
        def loaded(self,state):
            session=state.get('session_token') if isinstance(state,dict) else None
            if type(session) is not str or not re.fullmatch(r'[0-9a-f]{64}',session):raise ValueError('뷰어 연결 응답이 올바르지 않습니다.')
            if state.get('operation_busy'):raise ValueError('뷰어 작업이 실행 중입니다. 완료 후 새로고침하세요.')
            self.session=session;current=state.get('current');self.current=current.get('job_id') if isinstance(current,dict) else None
            saved=(current.get('settings',{}).get('snapshot') or {}) if isinstance(current,dict) else {};selected={r['asset_id']:r for r in saved.get('assets',[])}
            self.rows=[row for row in state.get('assets',[]) if row.get('enabled')];self.table.setRowCount(len(self.rows))
            for i,row in enumerate(self.rows):self.set_asset_row(i,row,selected.get(row['asset_id']))
            self.show_material(self.table.currentRow())
            sim=saved.get('simulation') or {};bake=saved.get('bake') or {}
            for key in ('count','seed','width','depth','seconds','friction','restitution','height_min','height_max'):
                source=sim if key in sim else bake
                if key in source:self.fields[key].setValue(source[key])
            self.fields['placement_jitter'].setChecked(bool(sim.get('placement_jitter',False)))
            for key,source in (('edges',sim),('resolution',bake),('normal',bake),('samples',bake)):
                if key in source:
                    box=self.fields[key];index=box.findData(source[key]) if key!='normal' else box.findText(source[key]);
                    if index>=0:box.setCurrentIndex(index)
            cap=state.get('capabilities') or {};self.fields['placement_jitter'].setEnabled(bool(cap.get('placement_jitter')));self.fields['edges'].model().item(2).setEnabled(bool(cap.get('seamless_periodic')))
            self.request('GET','api/designer-draft-state',None,self.draft_state_loaded)
        def draft_state_loaded(self,state):
            if type(state) is not dict or state.get('current_job_id')!=self.current:raise ValueError('뷰어 결과가 바뀌었습니다. 새로고침하세요.')
            revision=state.get('revision')
            if revision is not None and (type(revision) is not str or not _HEX32.fullmatch(revision)):raise ValueError('뷰어 draft revision이 올바르지 않습니다.')
            self.revision=revision
            self.ready=True
            self.status.setText('자산 '+str(len(self.rows))+'개 · 선택과 설정을 확인한 뒤 제출하세요.');self.submit.setEnabled(True)
        def send(self):
            try:
                if self.shutting_down:raise ValueError('Designer 플러그인을 종료하고 있습니다.')
                if getattr(panel,'_token',None) is not None:raise ValueError('Designer 패널의 현재 작업이 끝난 뒤 제출하세요.')
                chosen=[]
                for i,row in enumerate(self.rows):
                    if self.table.cellWidget(i,0).isChecked():chosen.append(dict(row,choice_scale=self.table.cellWidget(i,2).value(),choice_weight=self.table.cellWidget(i,3).value()))
                selected_ids={row['asset_id'] for row in chosen}
                if any(asset_id in selected_ids for asset_id,_slot in self.material_dirty):raise ValueError('선택한 자산에 미적용 재질 편집이 있습니다. 적용하거나 해당 슬롯 편집을 취소한 뒤 설정을 제출하세요.')
                f=self.fields
                sim={k:f[k].value() for k in ('count','seed','width','depth','seconds','friction','restitution')};sim['seed']=int(sim['seed']);sim['edges']=f['edges'].currentData();sim['placement_jitter']=f['placement_jitter'].isChecked()
                bake={k:f[k].value() for k in ('height_min','height_max')};bake.update(resolution=f['resolution'].currentData(),normal=f['normal'].currentText(),samples=f['samples'].currentData())
                if bake['height_max']<=bake['height_min']:raise ValueError('최대 높이는 최소 높이보다 커야 합니다.')
                body,revisions=build_draft(chosen,sim,bake);expected=self.current
                self.status.setText('선택 설정을 뷰어로 전송 중…')
                def received(value):
                    try:revision=verify_receipt(value,revisions,expected,body)
                    except ValueError:
                        raise
                    self.revision=revision
                    self.status.setText('제출 완료 · revision '+revision+' · Designer에서 Inspect한 Graph를 실행하세요.')
                    if hasattr(panel,'viewer_draft_status'):panel.viewer_draft_status.setText('Designer에서 제출된 viewer 설정 · revision '+revision)
                def health_ready(health):
                    viewer_runtime.validate_health(health,trusted_root)
                    envelope=dict(settings=body,expected_revision=self.revision,expected_current_job_id=expected,expected_asset_revisions=revisions)
                    self.request('POST','api/designer-draft',envelope,received)
                self.request('GET','api/viewer-health',None,health_ready)
            except Exception as error:self.status.setText(str(error))
    dialog=Dialog();panel._viewer_settings_dialog=dialog;dialog.show();return dialog
