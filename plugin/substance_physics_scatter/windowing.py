"""Presentation for a borrowed, verified native QDockWidget; never owns it."""
from PySide6 import QtCore, QtWidgets
import shiboken6


def idle(panel):
    return (getattr(panel, '_phase', None) == 'idle' and getattr(panel, '_token', None) is None
            and getattr(panel, 'process', None) is None and not getattr(panel, '_closing', False))


def floating_rect(available):
    width=min(520,available.width());height=min(720,available.height())
    return QtCore.QRect(available.x()+(available.width()-width)//2,
                        available.y()+(available.height()-height)//2,width,height)


class Window(QtWidgets.QDialog):
    """Owned nonmodal OS window. Closing never reaches the contained Panel."""
    def __init__(self,controller,parent):
        super().__init__(parent)
        self.controller=controller
        self.setWindowTitle('Physics Scatter')
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose,False)
        self.setSizeGripEnabled(True)

    def closeEvent(self,event):
        event.ignore();self.controller.hide()
        if self.controller.state.get('phase')!='stopping':self.controller.state['phase']='hidden'

    def reject(self):
        # Escape has the same hide-only semantics as the OS close button.
        self.controller.hide()
        if self.controller.state.get('phase')!='stopping':self.controller.state['phase']='hidden'


class Presentation(QtCore.QObject):
    def __init__(self,state,body,layout):
        native=body.parentWidget()
        if not isinstance(native,QtWidgets.QDockWidget) or not shiboken6.isValid(native) or native.widget() is not body:
            raise RuntimeError('Expected the existing native QDockWidget parent and exact body')
        owner=native.parentWidget()
        if not isinstance(owner,QtWidgets.QMainWindow) or not shiboken6.isValid(owner):
            raise RuntimeError('Expected the existing Designer main-window owner')
        super().__init__(body)
        self.state=state;self.body=body;self.native=native;self.layout=layout
        self.panel=None;self.float_initialized=False;self.separate=False
        self.transition=False;self.move_failed=False;self.redirect_pending=False
        self.window=Window(self,owner);self.window_layout=QtWidgets.QVBoxLayout(self.window)
        self.toolbar=QtWidgets.QWidget(body);buttons=QtWidgets.QHBoxLayout(self.toolbar)
        buttons.setContentsMargins(0,0,0,0)
        separate=QtWidgets.QPushButton('Separate window',self.toolbar)
        dock=QtWidgets.QPushButton('Dock panel',self.toolbar)
        buttons.addWidget(separate);buttons.addWidget(dock)
        separate.clicked.connect(lambda:self.move(True));dock.clicked.connect(lambda:self.move(False))
        self.scroll=QtWidgets.QScrollArea(body);self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumSize(320,280)
        self.scroll.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        native.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)
        native.setFeatures(native.features() | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
                           QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        native.installEventFilter(self)

    def attach(self,panel):
        if self.panel is panel:return
        if self.panel is not None or self.scroll.widget() is not None:raise RuntimeError('Presentation already owns another panel')
        self.layout.removeWidget(panel)
        try:
            destination=self.window_layout if self.separate else self.layout
            destination.addWidget(self.toolbar);destination.addWidget(self.scroll)
            self.scroll.setWidget(panel);self.panel=panel
        except Exception:
            if self.scroll.widget() is panel:self.scroll.takeWidget()
            self.layout.removeWidget(self.toolbar);self.layout.removeWidget(self.scroll)
            self.toolbar.hide();self.scroll.hide();self.layout.addWidget(panel);panel.show()
            raise
        self.toolbar.show();self.scroll.show()

    def detach(self,panel):
        if self.panel is not panel or self.scroll.widget() is not panel:raise RuntimeError('Presentation panel ownership differs')
        if self.scroll.takeWidget() is not panel:raise RuntimeError('Unexpected detached panel')
        self.panel=None

    def show(self):
        if self.separate:
            self.native.hide();self.window.show();self.window.raise_()
        else:
            self.window.hide();self.body.show();self.native.show();self.native.raise_()

    def hide(self):
        self.window.hide();self.native.hide()

    def move(self,floating):
        if self.move_failed:raise RuntimeError('Presentation transfer failed; refusing another reparent attempt')
        if self.transition or self.state.get('phase') == 'stopping' or self.panel is None or not idle(self.panel):
            if self.panel is not None:self.panel.message('Wait for the current operation to finish before moving the panel.')
            return
        if self.separate==floating:self.show();return
        source=self.window_layout if self.separate else self.layout
        destination=self.window_layout if floating else self.layout
        if self.scroll.widget() is not self.panel or source.indexOf(self.toolbar)<0 or source.indexOf(self.scroll)<0:
            self.move_failed=True;raise RuntimeError('Presentation container ownership differs')
        self.transition=True
        try:
            for widget in (self.toolbar,self.scroll):
                source.removeWidget(widget);destination.addWidget(widget)
            self.separate=floating
        except Exception:
            self.move_failed=True
            # Restore only our known children, never reparent the borrowed native dock.
            for widget in (self.toolbar,self.scroll):
                destination.removeWidget(widget);source.addWidget(widget);widget.show()
            raise
        finally:self.transition=False
        self.toolbar.show();self.scroll.show()
        if floating and not self.float_initialized:
            screen=self.native.screen()
            if screen is not None:self.window.setGeometry(floating_rect(screen.availableGeometry()))
            self.float_initialized=True
        self.show()

    def _redirect_native_show(self):
        self.redirect_pending=False
        if self.separate and not self.transition and self.state.get('phase')!='stopping' and self.panel is not None:
            self.show()
            self.state['phase']='ready'

    def eventFilter(self,watched,event):
        if watched is self.native:
            if event.type()==QtCore.QEvent.Type.Close:
                event.ignore();self.hide()
                if self.state.get('phase') != 'stopping':self.state['phase']='hidden'
                return True
            if event.type()==QtCore.QEvent.Type.Show and self.separate and not self.redirect_pending:
                # Designer's Windows menu opens the borrowed dock. Redirect after its show event.
                self.redirect_pending=True
                QtCore.QTimer.singleShot(0,self._redirect_native_show)
        return super().eventFilter(watched,event)
