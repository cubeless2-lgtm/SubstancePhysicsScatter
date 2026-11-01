import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter.maskio import decode_black
WORKER=ROOT/"build/Release/scatter_worker.exe"
def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
def png(data=b"\0\x7f",w=1,h=1,bits=8,color=0,interlace=0,compressed=None,before=(),between=(),after=()):
    header=struct.pack(">IIBBBBB",w,h,bits,color,0,0,interlace)
    stream=zlib.compress(data) if compressed is None else compressed
    parts=[b"\x89PNG\r\n\x1a\n",chunk(b"IHDR",header),*before,chunk(b"IDAT",stream),*between,chunk(b"IEND",b""),*after]
    return b"".join(parts)
class MaskDecoder(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix="scatter_mask_decoder ");self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def probe(self,data,success=True,**extra):
        image=self.root/"mask.png";image.write_bytes(data);path=self.root/"request.json"
        path.write_text(json.dumps(dict(schema_version=2,job_id="probe",operation="mask_probe",path=str(image),**extra)),encoding="utf-8")
        p=subprocess.run([str(WORKER),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=15)
        self.assertEqual(p.returncode==0,success,p.stdout+p.stderr)
        if not extra.get("fault") and not extra.get("reserved_work"):
            if success:decode_black(data)
            else:
                with self.assertRaises(ValueError):decode_black(data)
        return json.loads(p.stdout.splitlines()[-1])
    def test_png8_16_raw_values_orientation_and_nearest(self):
        values=(0,1,128,255,255,128,1,0);raw8=b"\0"+bytes(values[:4])+b"\0"+bytes(values[4:])
        raw16=b"\0"+b"".join(struct.pack(">H",v*257) for v in values[:4])+b"\0"+b"".join(struct.pack(">H",v*257) for v in values[4:])
        points=[[-1,1],[1,1],[-1,-1],[1,-1],[0,0],[1.01,0]]
        first=self.probe(png(raw8,4,2),points=points);second=self.probe(png(raw16,4,2,bits=16),points=points)
        self.assertEqual(first["pixels_sha256"],second["pixels_sha256"]);self.assertEqual(first["samples"],second["samples"])
        self.assertEqual(first["samples"],[0,65535,65535,0,257,0]);self.assertEqual(first["diagnostic"]["callback_calls"],1)
    def test_expected_minus_exact_plus_stored_and_huffman_hard_cap(self):
        exact=self.probe(png());d=exact["diagnostic"]
        self.assertEqual(d["expected"],2);self.assertEqual(d["inflate_end_calls"],1);self.assertEqual(d["callback_live_bytes"],0)
        self.assertEqual(exact["pixels_sha256"],hashlib.sha256(struct.pack(">H",127*257)).hexdigest())
        trailing=zlib.compressobj();normal_with_empty_final=trailing.compress(b"\0\x7f")+trailing.flush(zlib.Z_SYNC_FLUSH)+trailing.flush(zlib.Z_FINISH)
        self.assertEqual(self.probe(png(compressed=normal_with_empty_final))["pixels_sha256"],exact["pixels_sha256"])
        for raw in (b"\0",b"\0\1\2",b"\0"*65535):
            for level in (0,9):
                result=self.probe(png(compressed=zlib.compress(raw,level)),False);info=result["diagnostic"]
                self.assertEqual(info["expected"],2);self.assertEqual(info["callback_calls"],1)
                self.assertEqual(info["zlib_live_bytes"],0);self.assertEqual(info["callback_live_bytes"],0)
    def test_wrapper_trailer_stream_dictionary_and_filter_failures(self):
        raw=b"\0\1";base=zlib.compress(raw)
        raw_def=zlib.compressobj(wbits=-15);gzip=zlib.compressobj(wbits=31);dictionary=zlib.compressobj(zdict=b"dictionary")
        streams=[base[:-1],base[:-1]+bytes([base[-1]^1]),base+b"garbage",base+base,raw_def.compress(raw)+raw_def.flush(),gzip.compress(raw)+gzip.flush(),dictionary.compress(raw)+dictionary.flush()]
        for stream in streams:
            result=self.probe(png(compressed=stream),False)
            self.assertEqual(result["diagnostic"]["inflate_end_calls"],1);self.assertEqual(result["diagnostic"]["callback_live_bytes"],0)
        bad_filter=self.probe(png(b"\5\1"),False);self.assertEqual(bad_filter["diagnostic"]["reason"],0);self.assertEqual(bad_filter["diagnostic"]["callback_live_bytes"],0)
    def test_strict_chunks_limits_and_no_ancillary_inflate(self):
        compressed=zlib.compress(b"x"*(1024*1024));ancillary=[chunk(b"zTXt",b"key\0\0"+compressed),chunk(b"iCCP",b"profile\0\0"+compressed),chunk(b"iTXt",compressed)]
        baseline=self.probe(png());result=self.probe(png(before=ancillary))
        self.assertEqual(result["pixels_sha256"],baseline["pixels_sha256"]);self.assertEqual(result["diagnostic"]["callback_calls"],1)
        self.assertEqual(result["diagnostic"]["sanitized_bytes"],baseline["diagnostic"]["sanitized_bytes"])
        unknown=chunk(b"aaAa",b"x");bad_crc=unknown[:-1]+bytes([unknown[-1]^1])
        wrongs=[png(before=[bad_crc]),png(before=[chunk(b"ABCD",b"")]),png(before=[chunk(b"tRNS",b"\0\0")]),png(before=[chunk(b"PLTE",b"\0\0\0")]),png(interlace=1),png(color=2),png(bits=4),png(w=8193),png(w=8192,h=8192),png()[:-12],png()+b"x",png()[:20],png(before=[chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,0,0,0,0))]),png(between=[chunk(b"aaAa",b""),chunk(b"IDAT",b"")])]
        for image in wrongs:self.probe(image,False)
        self.probe(png(),False,reserved_work=512*1024*1024)
    def test_callback_ownership_and_allocation_failures(self):
        result=self.probe(png(),fault="precondition");self.assertTrue(result["precondition_unchanged"])
        for fault in ("out","init","internal"):
            result=self.probe(png(),False,fault=fault);d=result["diagnostic"]
            self.assertEqual(d["callback_live_bytes"],0);self.assertEqual(d["zlib_live_bytes"],0);self.assertEqual(d["inflate_end_calls"],0)

if __name__=="__main__":unittest.main(verbosity=2)
