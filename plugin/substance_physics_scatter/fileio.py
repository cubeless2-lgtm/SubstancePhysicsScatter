"""Logical paths stay in the protocol; extended Unicode paths are used only for Windows I/O."""
import os
from pathlib import Path

def io_path(path):
    value=os.fspath(path)
    if os.name!="nt":return Path(value)
    value=os.path.abspath(value)
    if value.startswith("\\\\?\\"):return Path(value)
    if value.startswith("\\\\"):return Path("\\\\?\\UNC\\"+value[2:])
    return Path("\\\\?\\"+value)

def logical_path(path):
    # Resolve through the extended path too: deep symlinks must participate in ownership checks.
    value=str(io_path(path).resolve())
    if os.name=="nt":
        if value.startswith("\\\\?\\UNC\\"):value="\\\\"+value[8:]
        elif value.startswith("\\\\?\\"):value=value[4:]
    return Path(value)
