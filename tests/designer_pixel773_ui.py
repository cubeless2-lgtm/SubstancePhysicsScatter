"""Fixed False/True real Panel Sim, Saved and last-good continuation probe."""
from pathlib import Path
import struct
path=Path(__file__).with_name('designer_viewer_live.py')
source=path.read_text(encoding='utf8')
old="or value['result']['poses']==self.initial['result']['poses']"
assert source.count(old)==1
source=source.replace(old,"or value['result']['execution']['physics_executed'] is not True")
old="write(WORK/'simulation-current.json',value);self.sim=copy.deepcopy(value)"
new="write(WORK/('true-current.json' if hasattr(self,'first_sim') else 'false-current.json'),value);self.sim=copy.deepcopy(value)"
assert source.count(old)==1;source=source.replace(old,new)
old="""            elif self.phase=='simulation_ready':
                if not self.continuation('rebake.json','rebake_256'):return
                if self.panel.resolution.findText('256')<0:self.panel.resolution.addItem('256')
                self.panel.resolution.setCurrentText('256');self.phase='wait_rebake';self.begin(True)
"""
new="""            elif self.phase=='simulation_ready':
                if not hasattr(self,'first_sim'):
                    if not self.continuation('inverse.json','simulate_true'):return
                    self.first_sim=copy.deepcopy(self.sim);E['false_job']=self.first_sim['job_id']
                    self.new_invert=True;self.edit_and_inspect()
                else:
                    if not self.continuation('rebake.json','rebake_256'):return
                    from substance_physics_scatter import maskio
                    png=__import__('runpy').run_path(str(ROOT/'tests/png_pixels.py'))
                    shape,a=png['decoded'](self.first_sim['request']['scatter_mask']['path'])
                    shape_b,b=png['decoded'](self.sim['request']['scatter_mask']['path'])
                    if shape!=(512,512,16,0) or shape_b!=shape:raise ValueError('Exact512 uint16 mask layout')
                    mismatch=sum(x[0]+y[0]!=65535 for x,y in zip(struct.iter_unpack('>H',a),struct.iter_unpack('>H',b)))
                    E['inverse_comparison']=dict(pixels=262144,mismatches=mismatch,tolerance=0)
                    E['true_job']=self.sim['job_id']
                    if mismatch:raise ValueError('Actual Panel masks are not exact inverses')
                    if self.panel.resolution.findText('256')<0:self.panel.resolution.addItem('256')
                    self.panel.resolution.setCurrentText('256');self.phase='wait_rebake';self.begin(True)
"""
assert source.count(old)==1;source=source.replace(old,new)
old="'output/designer_bridge/viewer-live'"
assert source.count(old)==1;source=source.replace(old,"'output/designer_bridge/pixel773-ui'")
scope={'__file__':str(path),'__name__':'__main__','struct':struct}
exec(compile(source,str(path),'exec'),scope)
REPORT=scope['REPORT']
