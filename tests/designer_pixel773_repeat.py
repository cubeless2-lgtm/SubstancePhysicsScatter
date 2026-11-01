"""One extra unchanged False compute to distinguish cache settling from edits."""
from pathlib import Path
import hashlib
path=Path(__file__).with_name('designer_pixel773_private.py')
source=path.read_text(encoding='utf8')
changes={
    "'output/designer_bridge/pixel773-private'":"'output/designer_bridge/pixel773-repeat'",
    "limits=dict(load=3,unload=3,compute=3,PNG=9,raw_reads=18)":"limits=dict(load=3,unload=3,compute=4,PNG=12,raw_reads=24)",
    "if E['compute']>=3:":"if E['compute']>=4:",
    "if E['PNG']>=9 or E['raw_reads']+2>18:":"if E['PNG']>=12 or E['raw_reads']+2>24:",
    "(('F0',False),('T',True),('F1',False))":"(('F0',False),('R',False),('T',True),('F1',False))",
}
for old,new in changes.items():
    if source.count(old)!=1:raise ValueError('Fixed repeat anchor differs: '+old)
    source=source.replace(old,new)
scope={'__file__':str(path),'__name__':'__main__'}
exec(compile(source,str(path),'exec'),scope)
REPORT=scope['REPORT']
