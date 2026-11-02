"""Conservative cleanup for a single import directory created by this request."""
import os
from pathlib import Path
import re
import shutil
import stat
from substance_physics_scatter.fileio import io_path,logical_path

def clean(work,folder,created_id):
    if type(created_id) is not str or not re.fullmatch('[0-9a-f]{32}',created_id):raise ValueError('Import cleanup identity differs')
    base=Path(os.path.abspath(work));expected=base/'imports'/created_id
    if Path(os.path.abspath(folder))!=expected:raise ValueError('Import cleanup path differs')
    resolved_base=logical_path(base);resolved=logical_path(expected)
    if resolved!=resolved_base/'imports'/created_id:raise ValueError('Import cleanup resolved path differs')
    # Reject junctions, symlinks and all other Windows reparse points instead of
    # following them, including dangling links and nested generated entries.
    for path in (base,base/'imports',expected):
        info=io_path(path).lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Import cleanup path is a link')
    if not io_path(expected).is_dir():raise ValueError('Import cleanup target is not a directory')
    todo=[expected]
    while todo:
        parent=todo.pop()
        with os.scandir(io_path(parent)) as entries:
            for entry in entries:
                info=entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Import cleanup contains a link')
                if stat.S_ISDIR(info.st_mode):todo.append(parent/entry.name)
                elif not stat.S_ISREG(info.st_mode):raise ValueError('Import cleanup contains a non-regular file')
    if logical_path(expected)!=resolved:raise ValueError('Import cleanup path changed')
    shutil.rmtree(io_path(expected))
