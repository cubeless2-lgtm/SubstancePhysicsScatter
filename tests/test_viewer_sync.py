"""Completion token binding used when a hidden viewer returns after an external job."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]

class ViewerSync(unittest.TestCase):
    def test_external_completion_requires_matching_current_and_no_pending_submit(self):
        script=r'''
import assert from 'node:assert/strict';
import {completedExternalToken,staleJobError,catalogSignature} from './web/viewer-sync.js';
const old={settings:{token:'old'}},fresh={settings:{token:'new'}};
assert.equal(completedExternalToken(fresh,{status:'completed',token:'new'},false),'new');
assert.equal(completedExternalToken(old,{status:'completed',token:'new'},false),null);
assert.equal(completedExternalToken(fresh,{status:'running',token:'new'},false),null);
assert.equal(completedExternalToken(fresh,{status:'completed',token:'new'},true),null);
assert.equal(completedExternalToken(null,{status:'completed',token:'new'},false),null);
assert.equal(staleJobError('old failure','old failure',{status:'completed',error:null}),true);
assert.equal(staleJobError('old failure','user message',{status:'completed',error:null}),false);
assert.equal(staleJobError('old failure','old failure',{status:'failed',error:'new failure'}),false);
const a={enabled:true,asset_id:'a',render_revision:'r',material_revision:'m',asset_revision:'old'};
assert.notEqual(catalogSignature([a]),catalogSignature([{...a,asset_revision:'new'}]));
assert.equal(catalogSignature([{...a,enabled:false}]),'');
'''
        p=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf8',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=ROOT/'local_review',timeout=10)
        self.assertEqual(p.returncode,0,p.stdout)

if __name__=='__main__':unittest.main()
