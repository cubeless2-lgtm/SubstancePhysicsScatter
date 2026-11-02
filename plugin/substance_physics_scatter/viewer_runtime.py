"""Local viewer launch inputs and unauthenticated checkout-identity checks."""
from pathlib import Path
import subprocess
import os
import socket
from .viewer_identity import root_sha256

APP='substance-physics-scatter-local-viewer'

def port_is_unbound(port):
    """Use the Windows kernel listener table; timeouts alone never prove a free port."""
    if os.name!='nt' or type(port) is not int or not 1024<=port<=65535:raise ValueError('Cannot verify local listener ownership')
    import ctypes
    from ctypes import wintypes
    class Row4(ctypes.Structure):
        _fields_=[('state',wintypes.DWORD),('address',wintypes.DWORD),('port',wintypes.DWORD),('remote_address',wintypes.DWORD),('remote_port',wintypes.DWORD),('pid',wintypes.DWORD)]
    class Row6(ctypes.Structure):
        _fields_=[('address',ctypes.c_ubyte*16),('scope',wintypes.DWORD),('port',wintypes.DWORD),('remote_address',ctypes.c_ubyte*16),('remote_scope',wintypes.DWORD),('remote_port',wintypes.DWORD),('state',wintypes.DWORD),('pid',wintypes.DWORD)]
    fn=ctypes.WinDLL('iphlpapi',use_last_error=True).GetExtendedTcpTable
    fn.argtypes=(ctypes.c_void_p,ctypes.POINTER(wintypes.ULONG),wintypes.BOOL,wintypes.ULONG,ctypes.c_int,wintypes.ULONG);fn.restype=wintypes.ULONG
    for family,row in ((socket.AF_INET,Row4),(socket.AF_INET6,Row6)):
        size=wintypes.ULONG(0);code=fn(None,ctypes.byref(size),False,family,3,0)
        if code not in (0,122) or size.value<4 or size.value>16*1024*1024:raise ValueError('Cannot inspect local TCP listeners')
        buffer=ctypes.create_string_buffer(size.value);code=fn(buffer,ctypes.byref(size),False,family,3,0)
        if code:raise ValueError('Local TCP listener list changed; retry')
        count=ctypes.c_uint32.from_buffer_copy(buffer.raw[:4]).value
        if 4+count*ctypes.sizeof(row)>size.value:raise ValueError('Invalid local TCP listener table')
        for index in range(count):
            item=row.from_buffer_copy(buffer,4+index*ctypes.sizeof(row))
            if item.state==2 and socket.ntohs(item.port & 0xffff)==port:return False
    return True

def checkout_root():
    return Path(__file__).resolve().parents[2]

def validate_health(value,root):
    if type(value) is not dict or value.get('application')!=APP or value.get('protocol_version')!=1 or value.get('project_root_sha256')!=root_sha256(root) or value.get('authentication')!='none_local_identity_only' or type(value.get('process_id')) is not int or value['process_id']<=0:
        raise ValueError('Port is occupied by an unknown service or another checkout; no process was changed')
    return value['process_id']

def launch(root,port):
    root=Path(root).resolve();viewer=root/'local_review';python=viewer/'.venv'/'Scripts'/'python.exe';script=viewer/'launch.py'
    for path in (python,script,viewer/'server.py',root/'plugin/substance_physics_scatter/ui.py'):
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Local viewer runtime is not installed. Build this source checkout using BUILDING.md; an sdplugin alone does not include the viewer.')
    if type(port) is not int or not 1024<=port<=65535:raise ValueError('Invalid local viewer port')
    return subprocess.Popen([str(python),str(script),'--source','--port',str(port)],cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0))
