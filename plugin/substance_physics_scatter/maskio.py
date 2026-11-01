"""Owned file snapshots and bounded raw grayscale PNG validation; no Designer imports."""
import hashlib,json,os,struct,uuid,zlib
from pathlib import Path
from .fileio import io_path,logical_path
POLICY=dict(format="png",interpretation="raw_linear_probability",sampling="nearest",placement="grid_rejection_v1")
MAX_FILE=64*1024*1024

def identity(descriptor):
    if descriptor is None:return None
    if not isinstance(descriptor,dict) or set(descriptor)-set(POLICY)-{"content_hash","path","source_name"}:raise ValueError("Unknown Mask descriptor field")
    if any(descriptor.get(k)!=v for k,v in POLICY.items()):raise ValueError("Unsupported Mask policy")
    digest=descriptor.get("content_hash")
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):raise ValueError("Invalid Mask hash")
    return dict(content_hash=digest,**POLICY)

def cache_path(root,digest):
    identity(dict(content_hash=digest,**POLICY));root=logical_path(root);path=logical_path(root/"inputs"/(digest+".png"))
    if not path.is_relative_to(root):raise ValueError("Mask cache escapes owned root")
    return path

def read(path,expected=None):
    size=io_path(path).stat().st_size
    if size>MAX_FILE:raise ValueError("Mask exceeds 64 MiB")
    with io_path(path).open("rb") as stream:data=stream.read(MAX_FILE+1)
    if len(data)!=size or io_path(path).stat().st_size!=size:raise ValueError("Mask changed during read")
    digest=hashlib.sha256(data).hexdigest()
    if expected is not None and digest!=expected:raise ValueError("Mask snapshot SHA mismatch")
    return data,digest

def decode_black(data):
    if len(data)>MAX_FILE or data[:8]!=b"\x89PNG\r\n\x1a\n":raise ValueError("Invalid Mask PNG")
    offset=8;header=None;parts=[];idat=False;ended=False;separated=False;compressed_size=0
    while offset<len(data):
        if len(data)-offset<12:raise ValueError("Truncated Mask chunk")
        length=struct.unpack(">I",data[offset:offset+4])[0];kind=data[offset+4:offset+8];end=offset+12+length
        if end>len(data):raise ValueError("Mask chunk exceeds file")
        content=data[offset+8:offset+8+length]
        if not all(65<=c<=90 or 97<=c<=122 for c in kind) or kind[2]&32:raise ValueError("Invalid Mask chunk type")
        if zlib.crc32(kind+content)&0xffffffff!=struct.unpack(">I",data[end-4:end])[0]:raise ValueError("Mask CRC mismatch")
        if header is None and kind!=b"IHDR":raise ValueError("Mask IHDR must be first")
        if kind==b"IHDR":
            if header is not None or length!=13:raise ValueError("Duplicate/invalid Mask IHDR")
            w,h,bits,color,compression,filter_method,interlace=struct.unpack(">IIBBBBB",content)
            if not 0<w<=8192 or not 0<h<=8192 or w*h>16777216 or bits not in (8,16) or color or compression or filter_method or interlace:raise ValueError("Mask requires non-interlaced grayscale PNG8/16")
            header=w,h,bits
        elif kind==b"IDAT":
            if separated:raise ValueError("Non-contiguous Mask IDAT")
            idat=True;compressed_size+=length
            if compressed_size>MAX_FILE:raise ValueError("Mask IDAT exceeds budget")
            parts.append(content)
        else:
            if idat:separated=True
            if kind==b"IEND":
                if length or not idat or end!=len(data):raise ValueError("Invalid Mask IEND")
                ended=True
            elif kind in (b"PLTE",b"tRNS") or not(kind[0]&32):raise ValueError("Unsupported Mask chunk/alpha")
        offset=end
        if ended:break
    if not ended:raise ValueError("Mask IEND missing")
    w,h,bits=header;bpp=bits//8;stride=w*bpp;expected=h*(stride+1)
    inflater=zlib.decompressobj()
    try:raw=inflater.decompress(b"".join(parts),expected)
    except zlib.error as error:raise ValueError("Mask zlib stream invalid") from error
    if len(raw)!=expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:raise ValueError("Mask inflate length/trailer mismatch")
    black=True;previous=bytearray(stride);offset=0
    for _ in range(h):
        mode=raw[offset];row=bytearray(raw[offset+1:offset+1+stride]);offset+=stride+1
        if mode>4:raise ValueError("Invalid Mask filter")
        if mode:
            for index in range(stride):
                a=row[index-bpp] if index>=bpp else 0;b=previous[index];c=previous[index-bpp] if index>=bpp else 0
                if mode==1:prediction=a
                elif mode==2:prediction=b
                elif mode==3:prediction=(a+b)//2
                else:
                    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);prediction=a if pa<=pb and pa<=pc else b if pb<=pc else c
                row[index]=(row[index]+prediction)&255
        black=black and not any(row);previous=row
    return black

def snapshot(root,value):
    if value is None:return None
    if isinstance(value,(str,Path)):config={"path":str(value)}
    elif isinstance(value,dict):config=dict(value)
    else:raise ValueError("Invalid Mask selection")
    enabled=config.pop("enabled",True)
    if type(enabled) is not bool:raise ValueError("Mask enabled must be bool")
    if not enabled:return None
    if set(config)-set(POLICY)-{"path","content_hash","source_name"}:raise ValueError("Unknown Mask selection field")
    if any(config.get(k,v)!=v for k,v in POLICY.items()):raise ValueError("Unsupported Mask policy")
    source=logical_path(config.get("path",""));cached_source=False
    if not io_path(source).is_file():
        if not config.get("content_hash"):raise ValueError("Choose an existing Mask PNG")
        source=cache_path(root,config["content_hash"]);cached_source=True
    owned_snapshot=bool(config.get("content_hash")) and source==cache_path(root,config["content_hash"])
    data,digest=read(source,config.get("content_hash") if cached_source or owned_snapshot else None);decode_black(data)
    target=cache_path(root,digest);io_path(target.parent).mkdir(parents=True,exist_ok=True)
    if io_path(target).exists():read(target,digest)
    else:
        temporary=target.parent/(uuid.uuid4().hex+".tmp")
        try:
            with io_path(temporary).open("xb") as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            read(temporary,digest);os.replace(io_path(temporary),io_path(target))
        finally:io_path(temporary).unlink(missing_ok=True)
    return dict(content_hash=digest,path=str(target),source_name=config.get("source_name",source.name),**POLICY)
