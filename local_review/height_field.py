"""Bounded grayscale16 PNG -> explicit little-endian uint16; never uses canvas."""
import hashlib,io,struct,zlib
from PIL import Image

def decode(raw):
    if len(raw)>32*1024*1024 or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Height PNG signature/budget')
    at=8;shape=None;chunks=[];data=[];started=False;closed=False;ended=False
    while at<len(raw):
        if len(raw)-at<12:raise ValueError('Height truncated chunk')
        count=int.from_bytes(raw[at:at+4],'big');typ=raw[at+4:at+8];stop=at+count+12
        if stop>len(raw) or zlib.crc32(raw[at+4:at+8+count])!=int.from_bytes(raw[at+8+count:stop],'big'):raise ValueError('Height CRC/length')
        if len(typ)!=4 or any(not (65<=x<=90 or 97<=x<=122) for x in typ) or typ[2]&32:raise ValueError('Height chunk type')
        if shape is None and typ!=b'IHDR':raise ValueError('Height IHDR first')
        if typ==b'IHDR':
            if shape is not None or count!=13:raise ValueError('Height IHDR singleton')
            w,h,bits,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',raw[at+8:at+21])
            if not 1<=w<=2048 or not 1<=h<=2048 or (bits,color,compression,filtering,interlace)!=(16,0,0,0,0):raise ValueError('Height requires bounded noninterlaced grayscale16')
            shape=(w,h)
        elif typ==b'IDAT':
            if closed:raise ValueError('Height contiguous IDAT required')
            started=True;data.append(raw[at+8:at+8+count])
        else:
            if started:closed=True
            if typ==b'IEND':
                if count or not started or stop!=len(raw):raise ValueError('Height IEND/trailing bytes')
                ended=True
            elif typ in (b'PLTE',b'tRNS') or not typ[0]&32:raise ValueError('Height unsupported critical/alpha chunk')
        if typ in (b'IHDR',b'IDAT',b'IEND'):chunks.append(raw[at:stop])
        at=stop
    if not ended:raise ValueError('Height missing IEND')
    w,h=shape;expected=h*(w*2+1);decoder=zlib.decompressobj();scan=decoder.decompress(b''.join(data),expected+1)
    if len(scan)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError('Height exact inflate size/trailer')
    if any(scan[row*(w*2+1)]>4 for row in range(h)):raise ValueError('Height PNG filter')
    del scan
    with Image.open(io.BytesIO(raw[:8]+b''.join(chunks))) as image:
        image.load()
        if image.size!=(w,h) or image.mode not in ('I;16','I;16B','I;16L','I'):raise ValueError('Height decoder type')
        be=image.tobytes('raw','I;16B')
    if len(be)!=w*h*2:raise ValueError('Height decoded length')
    le=bytearray(len(be));le[0::2]=be[1::2];le[1::2]=be[0::2];le=bytes(le)
    return dict(width=w,height=h,dtype='uint16',byte_order='little',row_order='PNG top row -> canonical +Y',source_png_sha256=hashlib.sha256(raw).hexdigest(),decoded_sha256=hashlib.sha256(le).hexdigest(),byte_length=len(le)),le
