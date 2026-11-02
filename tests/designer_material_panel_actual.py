"""Actual Designer Qt material editor, CAS conflict and source preservation lane.

Uses the isolated viewer only; the coordinator must start port 8879.
"""
from pathlib import Path
import copy,hashlib,importlib,json,time,traceback,types,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'output/material-panel-actual'/uuid.uuid4().hex[:12];WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json';report={'status':'scheduled','work':str(WORK)}
def write():REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
def request(path,data=None,headers=None):
 req=urllib.request.Request('http://127.0.0.1:8879'+path,data=data,headers=headers or {},method='POST' if data is not None else 'GET')
 with urllib.request.urlopen(req,timeout=10) as response:return json.loads(response.read(2*1024*1024))
write()
from PySide6 import QtCore,QtGui
from substance_physics_scatter import ui,viewer_settings,lifecycle
importlib.reload(ui);importlib.reload(viewer_settings)
registry=lifecycle.qt_registry();canonical=registry.get('panel');state={'panel':None,'dialog':None,'timer':None,'phase':'load','started':time.monotonic()}
def finish(status,error=None):
 if state['timer'] is not None:state['timer'].stop()
 dialog=state['dialog'];panel=state['panel']
 if dialog is not None and (dialog.reply is not None or dialog.upload_future is not None):report.update(status='FAIL',error='Active owned dialog preserved');write();return
 if dialog is not None:
  try:dialog.close()
  except BaseException as e:status='FAIL';report['dialog_cleanup']=repr(e)
 if panel is not None:
  try:panel.close();panel.deleteLater()
  except BaseException as e:status='FAIL';report['panel_cleanup']=repr(e)
 if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
 report['status']=status
 if error:report['traceback']=error
 write();registry.pop('_material_panel_actual',None)
def poll():
 try:
  if time.monotonic()-state['started']>180:raise TimeoutError('Material panel smoke timed out')
  dialog=state['dialog']
  if dialog.reply is not None or dialog.upload_future is not None:return
  if state['phase']=='load':
   if not dialog.ready:raise ValueError('Settings not ready: '+dialog.status.text())
   eligible=[i for i,row in enumerate(dialog.rows) if row.get('metadata',{}).get('material_ready') and row.get('metadata',{}).get('material_records')]
   if not eligible:raise ValueError('No material-ready isolated asset')
   index=eligible[0];dialog.table.setCurrentCell(index,1);dialog.show_material(index);row=dialog.rows[index]
   state.update(index=index,asset_id=row['asset_id'],old_asset_revision=row['asset_revision'],before_job=(request('/api/state').get('current') or {}).get('job_id'),before_draft=request('/api/designer-draft-state'))
   color=uuid.uuid4().bytes;image=QtGui.QImage(512,512,QtGui.QImage.Format.Format_RGBA8888);image.fill(QtGui.QColor(color[0],color[1],color[2],255));path=WORK/'material-test.png'
   if not image.save(str(path),'PNG'):raise ValueError('Could not create 512 texture fixture')
   state['texture']=path;state['texture_sha']=hashlib.sha256(path.read_bytes()).hexdigest();state['old_ids']={x['texture_id'] for x in row.get('texture_options',[])}
   state['phase']='upload';dialog.upload_textures([str(path)])
   if dialog.upload_future is None and dialog.reply is None:raise ValueError('Texture upload did not start: '+dialog.status.text())
   return
  if state['phase']=='upload':
   row=dialog.rows[state['index']]
   if not dialog.status.text().startswith('텍스처 추가 완료'):raise ValueError('Texture upload failed: '+dialog.status.text())
   new=[x['texture_id'] for x in row.get('texture_options',[]) if x['texture_id'] not in state['old_ids']]
   if len(new)!=1 or row['asset_revision']==state['old_asset_revision']:raise ValueError('Texture catalog revision missing')
   tid=new[0];state['texture_id']=tid
   for role in ('base_color','roughness','normal'):
    box=dialog.material_fields[role]['texture'];i=box.findData(tid)
    if i<0:raise ValueError('Uploaded texture absent from selector')
    box.setCurrentIndex(i)
   dialog.material_fields['roughness']['channel'].setCurrentIndex(dialog.material_fields['roughness']['channel'].findData('g'))
   dialog.material_fields['normal']['normal_convention'].setCurrentIndex(dialog.material_fields['normal']['normal_convention'].findData('DirectX'))
   state['phase']='preview';return
  if state['phase']=='preview':
   image=dialog.material_fields['roughness']['preview'].pixmap()
   if image is None or image.isNull():
    if dialog.preview_replies:return
    raise ValueError('Packed channel preview unavailable')
   report['packed_channel_preview']=True
   state['phase']='apply';dialog.apply_material()
   if dialog.reply is None:raise ValueError('Material apply did not start: '+dialog.status.text())
   return
  if state['phase']=='apply':
   if not dialog.status.text().startswith('재질 연결 적용 완료'):raise ValueError('Material apply failed: '+dialog.status.text())
   row=dialog.rows[state['index']];record=row['metadata']['material_records'][0]
   if record['base_color_texture']['texture_id']!=state['texture_id'] or record['roughness_texture']['channel']!='g' or record['normal_texture']['normal_convention']!='DirectX':raise ValueError('Material result bindings differ')
   dialog.material_fields['roughness']['channel'].setCurrentIndex(dialog.material_fields['roughness']['channel'].findData('b'))
   state['draft_before']=copy.deepcopy(dialog.material_drafts[(state['asset_id'],dialog.material_slot_id)])
   dialog.table.cellWidget(state['index'],0).setChecked(True);dialog.send()
   if dialog.reply is not None or '미적용 재질' not in dialog.status.text():raise ValueError('Dirty material did not block simulation draft')
   server=request('/api/state');headers={'X-Review-Token':server['session_token'],'X-Asset-Revision':row['asset_revision'],'Content-Type':'application/json'}
   request('/api/assets/'+state['asset_id']+'/material',json.dumps({'bindings':{'0':{'base_color':{'mode':'none'}}}}).encode(),headers)
   state['phase']='conflict';dialog.apply_material()
   if dialog.reply is None:raise ValueError('Conflict test did not start')
   return
  if state['phase']=='conflict':
   key=(state['asset_id'],dialog.material_slot_id)
   if dialog.material_drafts.get(key)!=state['draft_before'] or '편집값은 유지' not in dialog.status.text():raise ValueError('CAS conflict did not preserve edit: '+dialog.status.text())
   state['phase']='refresh';dialog.refresh_material()
   if dialog.reply is None:raise ValueError('Refresh did not start')
   return
  if state['phase']=='refresh':
   key=(state['asset_id'],dialog.material_slot_id)
   refreshed=dialog.material_drafts.get(key) or {}
   if refreshed.get('roughness')!=state['draft_before']['roughness'] or refreshed.get('base_color')!={'mode':'none'} or refreshed.get('normal')!=state['draft_before']['normal'] or '최신 자산 확인 완료' not in dialog.status.text():raise ValueError('Refresh lost edited role or did not adopt other-window base color: '+dialog.status.text())
   state['phase']='reapply';dialog.apply_material()
   if dialog.reply is None:raise ValueError('Reapply did not start')
   return
  if state['phase']=='reapply':
   if not dialog.status.text().startswith('재질 연결 적용 완료'):raise ValueError('Material reapply failed: '+dialog.status.text())
   row=dialog.rows[state['index']];record=row['metadata']['material_records'][0]
   if record['roughness_texture']['channel']!='b' or record['normal_texture']['normal_convention']!='DirectX' or record['base_color_texture'] is not None:raise ValueError('Reapply overwrote other window base color or changed bindings')
   dialog.material_fields['roughness']['channel'].setCurrentIndex(dialog.material_fields['roughness']['channel'].findData('g'))
   state['overlap_draft']=copy.deepcopy(dialog.material_drafts[(state['asset_id'],dialog.material_slot_id)])
   server=request('/api/state');headers={'X-Review-Token':server['session_token'],'X-Asset-Revision':row['asset_revision'],'Content-Type':'application/json'}
   competing={'mode':'texture','texture_id':state['texture_id'],'channel':'r','color_space':'linear','wrap':'repeat'}
   request('/api/assets/'+state['asset_id']+'/material',json.dumps({'bindings':{'0':{'roughness':competing}}}).encode(),headers)
   state['phase']='overlap';dialog.apply_material()
   if dialog.reply is None:raise ValueError('Overlap test did not start')
   return
  if state['phase']=='overlap':
   if '편집값은 유지' not in dialog.status.text():raise ValueError('Overlap conflict did not preserve edit: '+dialog.status.text())
   state['phase']='overlap_refresh';dialog.refresh_material()
   if dialog.reply is None:raise ValueError('Overlap refresh did not start')
   return
  if state['phase']=='overlap_refresh':
   key=(state['asset_id'],dialog.material_slot_id)
   if dialog.material_drafts.get(key)!=state['overlap_draft'] or state['asset_id'] not in dialog.material_conflict_assets:raise ValueError('Same-role conflict was not detected')
   dialog.apply_material()
   if dialog.reply is not None or '동일 역할' not in dialog.status.text():raise ValueError('Same-role conflict was not blocked')
   dialog.load()
   if dialog.reply is not None or '미적용 재질' not in dialog.status.text() or dialog.material_drafts.get(key)!=state['overlap_draft']:raise ValueError('Dirty asset refresh was not blocked/preserved')
   dialog.discard_material()
   server=request('/api/state')
   if (server.get('current') or {}).get('job_id')!=state['before_job'] or request('/api/designer-draft-state')!=state['before_draft']:raise ValueError('Previous current or draft changed')
   if hashlib.sha256(state['texture'].read_bytes()).hexdigest()!=state['texture_sha']:raise ValueError('Source texture was modified')
   report.update(texture_upload=True,source_texture_preserved=True,manual_basecolor=True,packed_channel_g_then_b=True,directx_normal=True,cas_conflict_preserved_edit=True,different_role_preserved=True,same_role_conflict_blocked=True,dirty_draft_blocked=True,dirty_refresh_blocked=True,explicit_refresh_reapply=True,previous_current_and_draft_preserved=True,canonical_preserved=True);finish('PASS')
 except BaseException:finish('FAIL',traceback.format_exc())
try:
 panel=ui.Panel();state['panel']=panel;panel.local_viewer_url=types.MethodType(lambda self:'http://127.0.0.1:8879/',panel)
 state['dialog']=viewer_settings.open_viewer_settings(panel,expected_root=ROOT)
 timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(100);timer.timeout.connect(poll);registry['_material_panel_actual']=state;timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
