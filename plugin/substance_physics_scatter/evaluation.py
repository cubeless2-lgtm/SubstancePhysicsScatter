"""UI-thread evaluation transactions with temporary current-process affinity.

The selected synchronous scope runs on the lowest allowed logical CPU.
This restricts OS scheduling; it does not select a Substance engine or guarantee
engine thread1 behavior. Unsupported platforms/APIs fail before computation.
"""
import ctypes
from ctypes import wintypes
import os
from contextlib import contextmanager


class AffinityRestorationError(RuntimeError):
    """The original process mask could not be restored and verified exactly."""


def _assert_environment(graph=None):
    if os.name != 'nt':
        raise RuntimeError('Scoped graph evaluation requires Windows affinity APIs')
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('Graph evaluation requires the Designer UI thread')
    if graph is not None:
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        if not isinstance(graph, SDSBSCompGraph):
            raise TypeError('An owned SDSBSCompGraph is required')


class _ProcessAffinity:
    def __init__(self):
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.GetCurrentProcess.argtypes = []
        api.GetCurrentProcess.restype = wintypes.HANDLE
        api.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        api.GetProcessAffinityMask.restype = wintypes.BOOL
        api.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        api.SetProcessAffinityMask.restype = wintypes.BOOL
        self.api = api
        # Current-process pseudo handle cannot be recycled to a foreign PID and
        # must not be closed. No PID lookup, other process or persistent setting.
        self.handle = api.GetCurrentProcess()

    def get(self):
        process, system = ctypes.c_size_t(), ctypes.c_size_t()
        if not self.api.GetProcessAffinityMask(self.handle, ctypes.byref(process), ctypes.byref(system)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not process.value or not system.value or process.value & system.value != process.value:
            raise RuntimeError('Current process affinity is unavailable or outside its system mask')
        return process.value

    def set(self, mask):
        if not self.api.SetProcessAffinityMask(self.handle, mask):
            raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def evaluation_scope():
    """Synchronous UI transaction; restore its original mask for BaseException.

No processEvents, retry, fallback, graph mutation or retained SDK wrapper. If
restoration fails, raise AffinityRestorationError; an original compute exception
remains in the exception context instead of being reported as successful.
"""
    _assert_environment()
    affinity = _ProcessAffinity()
    original = affinity.get()
    lowest = original & -original
    changed = original != lowest
    try:
        if changed:
            # The finally also covers a setter that mutates and then raises.
            affinity.set(lowest)
        if affinity.get() != lowest:
            raise RuntimeError('Restricted process affinity readback differs')
        yield
    finally:
        try:
            if changed:
                affinity.set(original)
            observed = affinity.get()
            if observed != original:
                raise RuntimeError(f'Expected affinity {original}, observed {observed}')
        except BaseException as error:
            raise AffinityRestorationError(f'Original process affinity {original} restoration failed: {error}') from error


def compute_graph(graph):
    """Compute once in an affinity scope; nested scopes preserve outer mask1."""
    if graph is None:
        raise TypeError('An owned SDSBSCompGraph is required')
    _assert_environment(graph)
    with evaluation_scope():
        return graph.compute()
