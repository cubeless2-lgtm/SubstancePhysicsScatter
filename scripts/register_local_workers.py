"""Explicitly register the three freshly built local worker binaries."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin'))
from substance_physics_scatter.local_workers import register
if __name__=='__main__':
    print('Registering locally built binaries as trusted on this machine; this does not prove those binaries were compiled from the fingerprint material and is not an independent review.')
    for row in register():print(row['mode'],row['fingerprint'],row['sha256'])
