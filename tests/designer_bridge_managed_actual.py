"""Fixed real-Qt bridge lifecycle check; no graph, pixel, widget or worker mutations."""
from pathlib import Path
import json
import time
import traceback
import uuid
from PySide6 import QtCore
from substance_physics_scatter import bridge
from substance_physics_scatter.errors import HOST_ERRORS

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/managed-actual'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json'
result=dict(status='running',computer_use=False,compute=0,worker=0,package_mutations=0,
            scope='Real Qt deferred stop, explicit recovery, and forced-clock expiry rotation; no one-hour wall-clock wait or crash-recovery claim',rows=[])
def write():
    temp=REPORT.with_suffix('.tmp')
    temp.write_text(json.dumps(result,indent=2),encoding='utf8');temp.replace(REPORT)
def row(label):
    value=bridge.status();result['rows'].append(dict(label=label,value=value));write();return value
def require(condition,message):
    if not condition:raise RuntimeError(message)
def failed():
    result.update(status='error',traceback=traceback.format_exc());write()

manager=bridge._manager(ROOT)
original=manager.queue
before=row('inside_handler')
require(before['managed'] and before['busy'] and before['timer_active'],'Managed executing bridge required')
session=before['session']
bridge.stop('verification_stop')
stopping=row('stop_deferred_inside_handler')
require(stopping['busy'] and stopping['stop_latched'] and stopping['status']=='stopping','Stop was not deferred')
bridge.ensure_auto()
require(manager.queue is original and manager.session==session and manager.latched,'Implicit init replaced or resumed executing stop')

def observe_expiry():
    try:
        value=row('after_forced_clock_expiry')
        require(value['status']=='listening' and value['timer_active'] and not value['stop_latched'],'Expired managed session did not recover')
        require(value['session']!=result['resumed_session'] and value['last_session']['reason']=='expired','Expiry rotation identity/reason differs')
        require(manager.queue.maximum==128 and manager.queue.expires>time.monotonic(),'Fresh session budget not restored')
        result.update(status='pass',expiry_was_forced=True);write()
    except HOST_ERRORS:failed()

def observe_stop_and_resume():
    try:
        value=row('after_handler_return')
        require(value['status']=='stopped' and not value['timer_active'] and not value['busy'],'Handler did not settle to stopped')
        bridge.ensure_auto()
        require(manager.queue is original and manager.latched,'Implicit initialization cleared explicit stop')
        value=bridge.resume_auto(ROOT);result['resumed_session']=value['session']
        require(value['session']!=session and not value['stop_latched'] and manager.timer.isActive(),'Explicit resume failed')
        row('explicit_resume')
        # Test-owned injection changes time only; the next genuine Qt poll must rotate.
        manager.queue.expires=time.monotonic()-1
        QtCore.QTimer.singleShot(750,observe_expiry)
    except HOST_ERRORS:failed()

QtCore.QTimer.singleShot(750,observe_stop_and_resume)
result['status']='awaiting_real_qt_callbacks';write()
