"""Choose one fixed Designer smoke lane while the file queue is idle. No SDK."""
from pathlib import Path
import argparse,json,os,runpy,uuid

ROOT=Path(__file__).resolve().parents[1]
_router=ROOT/'tests/designer_smoke_routes.py'
if _router.is_symlink() or not _router.resolve().is_relative_to(ROOT):raise ValueError('Smoke router escapes project')
ROUTER=runpy.run_path(str(_router))

def select(lane):
    root=ROUTER['project_root']()
    if root!=ROOT.resolve():raise ValueError('Smoke selector project root differs')
    ROUTER['target'](root,lane)
    directory=ROUTER['owned'](root,root/'output/designer_bridge');directory.mkdir(parents=True,exist_ok=True)
    def idle():
        for name in ('request.json','processing.json'):
            path=directory/name
            if path.exists() or path.is_symlink():raise ValueError('A Designer request is pending/running; selection unchanged')
    idle();path=ROUTER['owned'](root,directory/'smoke_selection.json');temporary=directory/('smoke_selection_'+uuid.uuid4().hex+'.tmp')
    raw=(json.dumps({'lane':lane},ensure_ascii=True,separators=(',',':'))+'\n').encode('utf8')
    try:
        with temporary.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        idle();ROUTER['owned'](root,path);os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return dict(lane=lane,selection=str(path),fixed_target=ROUTER['ROUTES'][lane])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('lane',choices=tuple(ROUTER['ROUTES']));args=parser.parse_args()
    try:result=select(args.lane)
    except (OSError,ValueError,TypeError) as error:raise SystemExit(str(error)) from None
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
