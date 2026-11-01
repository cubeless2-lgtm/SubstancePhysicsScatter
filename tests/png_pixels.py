"""Decode non-interlaced 8/16-bit PNG samples for exact host/worker cross-checks."""
from pathlib import Path
import hashlib,struct,zlib
from substance_physics_scatter.fileio import io_path
def decoded(path):
    content=io_path(path).read_bytes();offset=8;compressed=bytearray();header=None
    while offset+12<=len(content):
        size=struct.unpack(">I",content[offset:offset+4])[0];kind=content[offset+4:offset+8];data=content[offset+8:offset+8+size]
        if kind==b"IHDR":header=struct.unpack(">IIBBBBB",data)
        if kind==b"IDAT":compressed.extend(data)
        offset+=12+size
    w,h,bits,color,_,_,interlace=header
    channels={0:1,2:3,6:4}[color]
    if interlace or bits not in (8,16):raise ValueError("Unsupported PNG")
    bpp=channels*bits//8;stride=w*bpp;raw=zlib.decompress(compressed);result=bytearray();previous=bytearray(stride);position=0
    for row in range(h):
        filter=raw[position];position+=1;line=bytearray(raw[position:position+stride]);position+=stride
        for x in range(stride):
            a=line[x-bpp] if x>=bpp else 0;b=previous[x];c=previous[x-bpp] if x>=bpp else 0
            if filter==1:prediction=a
            elif filter==2:prediction=b
            elif filter==3:prediction=(a+b)//2
            elif filter==4:
                p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);prediction=a if pa<=pb and pa<=pc else b if pb<=pc else c
            elif filter==0:prediction=0
            else:raise ValueError("Invalid PNG filter")
            line[x]=(line[x]+prediction)&255
        result.extend(line);previous=line
    return (w,h,bits,color),bytes(result)
def signature(path):
    header,pixels=decoded(path)
    return {"header":header,"decoded_sha256":hashlib.sha256(pixels).hexdigest()}
