"""Owned handoff destinations; reject junctions before any file mutation."""
import os
import re
import stat
from pathlib import Path


def owned_external(package_path, graph_identifier, job_id, jobs_directory):
    package=Path(os.path.abspath(package_path))
    if type(graph_identifier) is not str or not re.fullmatch(r'scatter_[0-9a-f]{32}',graph_identifier) or type(job_id) is not str or not re.fullmatch(r'[0-9a-f]{32}',job_id):
        raise ValueError('Invalid owned handoff identifier')
    base=package.parent/(package.stem+'_PhysicsScatter')/graph_identifier
    if Path(os.path.abspath(jobs_directory))!=base:
        raise ValueError('Handoff result directory differs from the selected SBS graph')
    target=base/'external'/job_id
    cursor=Path(target.anchor)
    for component in target.parts[1:]:
        cursor=cursor/component
        try:entry=cursor.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(entry.st_mode) or getattr(entry,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
            raise ValueError('Handoff path contains a link or reparse point')
    if target.resolve()!=target:
        raise ValueError('Resolved handoff path differs from the SBS-owned path')
    return target
