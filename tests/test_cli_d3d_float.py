"""EXR bit transport and fixed CLI lifecycle fakes; never launch CLI/SDK."""
from pathlib import Path
import importlib.util,json,struct,tempfile,unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
INFO='GRAPH-URL pkg://vertical_noise\n INPUT $outputsize INTEGER2\n INPUT $randomseed INTEGER1\n INPUT Disorder FLOAT1\n OUTPUT Vertical_Noise\n'

def load():
    spec=importlib.util.spec_from_file_location('cli_float_pure',ROOT/'tests/designer_cli_d3d_float.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def exr(words,channels=('Y',),pixel_type=2,compression=0,window=(0,0,511,255)):
    def attr(name,kind,data):return name.encode()+b'\0'+kind.encode()+b'\0'+struct.pack('<i',len(data))+data
    ch=b''.join(n.encode()+b'\0'+struct.pack('<iB3sii',pixel_type,0,b'\0'*3,1,1) for n in channels)+b'\0'
    header=struct.pack('<II',20000630,2)+attr('channels','chlist',ch)+attr('compression','compression',bytes([compression]))+attr('dataWindow','box2i',struct.pack('<4i',*window))+attr('displayWindow','box2i',struct.pack('<4i',*window))+attr('lineOrder','lineOrder',b'\0')+attr('pixelAspectRatio','float',struct.pack('<f',1))+attr('screenWindowCenter','v2f',struct.pack('<2f',0,0))+attr('screenWindowWidth','float',struct.pack('<f',1))+b'\0'
    chunks=[];offsets=[];position=len(header)+256*8
    for y in range(256):
        row=words[y*2048:(y+1)*2048];block=b''.join(struct.pack('<I',0x3f800000)*512 if n=='A' else row for n in channels);chunk=struct.pack('<ii',y,len(block))+block;offsets.append(position);chunks.append(chunk);position+=len(chunk)
    return header+struct.pack('<256Q',*offsets)+b''.join(chunks)

class FloatCLI(unittest.TestCase):
    def test_float_words_preserve_signed_zero_nan_payload_and_grayscale_planes(self):
        p=load();words=struct.pack('<8I',0,0x80000000,0x7fc12345,0x7f800000,0xff800000,0x3f000000,1,0x3f800000)*(512*256//8)
        for channels in (('Y',),('A','B','G','R')):
            decoded,metadata=p.exr_words(exr(words,channels));self.assertEqual(decoded,words);self.assertEqual(metadata['pixel_type'],'FLOAT32')
        for kwargs in ({'pixel_type':1},{'compression':3},{'window':(0,0,511,511)}):
            with self.assertRaises(ValueError):p.exr_words(exr(words,**kwargs))
        with self.assertRaises(ValueError):p.exr_words(exr(words)+b'trailer')
    def test_info_and_argv_are_closed_float_d3d_and_independent_cache(self):
        p=load();mapping=p.info_mapping(INFO);commands=[p.render_argv('one.sbsar',mapping,Path('out')/label,label,value,Path('cache')/label) for label,value in p.STEPS]
        self.assertEqual(len({c[c.index('--cache-dir')+1] for c in commands}),3)
        self.assertEqual({c[c.index('--input')+1] for c in commands},{'one.sbsar'})
        for c in commands:
            self.assertEqual(c[c.index('--output-bit-depth')+1],'32f');self.assertEqual(c[c.index('--output-format')+1],'exr');self.assertEqual(c[c.index('--exr-format-compression')+1],'none');self.assertIn('--exr-format-use-float',c);self.assertEqual(c[c.index('--engine')+1],str(p.ENGINE));self.assertNotIn('png',c)
        for bad in (INFO.replace('Disorder FLOAT1','Disorder INTEGER1'),INFO.replace(' INPUT Disorder FLOAT1\n',''),INFO+' INPUT arbitrary FLOAT1\n',INFO+' OUTPUT Vertical_Noise\n'):
            with self.assertRaises(ValueError):p.info_mapping(bad)
    def test_actual_main_fake_cook_info_three_renders_and_missing_input_stop(self):
        p=load();helper=p.runpy.run_path(str(p.OLD/'bounded_process.py'));original_pins=p.PINS
        with tempfile.TemporaryDirectory() as directory:
            p.ROOT=Path(directory);p.PINS={p.SOURCE:original_pins[p.SOURCE]}
            for valid in (True,False):
                calls=[]
                def fake(argv,command_dir,timeout):
                    calls.append(argv);self.assertEqual(timeout,120);command_dir.mkdir(parents=True);stdout=command_dir/'stdout.bin';stdout.write_bytes(b'')
                    if argv[0]==str(p.COOK):(Path(argv[argv.index('--output-path')+1])/'archive.sbsar').write_bytes(b'one fixed fake cooked archive')
                    elif argv[1]=='info':stdout.write_text(INFO if valid else INFO.replace('Disorder FLOAT1','Disorder INTEGER1'),encoding='utf8')
                    else:
                        output=Path(argv[argv.index('--output-path')+1]);label=Path(argv[argv.index('--output-name')+1]).stem;reference='N50' if label=='N50' else 'N0';words=(p.SDK/(reference+'-before.raw')).read_bytes();(output/(label+'.exr')).write_bytes(exr(words))
                    return dict(status='completed',owned_child_active=False,reader_threads_alive=0,logs={'stdout':{'path':str(stdout)}})
                context=dict(helper,run=fake)
                with mock.patch.object(p,'preflight'),mock.patch.object(p.runpy,'run_path',return_value=context):report=p.main(True)
                value=json.loads(report.read_bytes());self.assertTrue(value['frozen_inputs_unchanged']);self.assertTrue(value['source_copy_unchanged']);self.assertTrue(value['archive_unchanged'])
                if valid:
                    self.assertEqual((len(calls),value['cook'],value['info'],value['render']),(5,1,1,3));self.assertEqual(value['status'],'CLI_float_observation_complete');self.assertTrue(value['CLI_return_comparison']['exact']);self.assertFalse(value['original_SDK_failure_resolved']);self.assertFalse(value['outputs'][2]['SDK_comparison']['exact'])
                else:self.assertEqual(len(calls),2);self.assertEqual(value['render'],0);self.assertEqual(value['status'],'failed')

if __name__=='__main__':unittest.main()
