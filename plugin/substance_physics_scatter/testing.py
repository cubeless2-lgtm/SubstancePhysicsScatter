"""Small host-independent lifetime helper for isolated Designer test widgets."""
from contextlib import contextmanager

@contextmanager
def isolated_panel(factory):
    panel=factory()
    try:
        yield panel
    finally:
        try:
            panel.close()
        finally:
            panel.deleteLater()
