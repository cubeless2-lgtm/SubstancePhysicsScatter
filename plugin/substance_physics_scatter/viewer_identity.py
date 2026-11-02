"""Non-authenticating local viewer identity for checkout selection."""
import hashlib
import os
from .fileio import logical_path

APPLICATION='substance-physics-scatter-local-viewer'
PROTOCOL_VERSION=1
AUTHENTICATION='none_local_identity_only'

def root_sha256(root):
    return hashlib.sha256(os.path.normcase(str(logical_path(root))).encode('utf-8')).hexdigest()
