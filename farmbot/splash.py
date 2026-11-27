"""COCFARM's loading screen, shown while the window is built (a first start
from a cold disk can take several seconds). Only Qt is imported here, so it
can show before the rest of COCFARM loads."""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QEventLoop, QObject, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from farmbot import __version__

LOGO = Path(__file__).parent / "assets" / "cocfarm.png"
WIDTH, HEIGHT = 420, 300
RADIUS, WINDOW_RADIUS = 12, 8  # the card's corners, and a Windows 11 window's
BACKGROUND = QColor("#202020")  # the window's dark theme
BORDER = QColor("#3a3a3a")
ACCENT = QColor("#4c9aff")
TEXT = QColor("#ffffff")
FAINT = QColor("#a0a0a0")

# Leaving it: the card grows into the window (to its size and place) while
# what's on it fades and the logo grows to GROW times its size; then the
# window is shown under it and the card fades away.
GROW = 1.5
GROW_MS = 380
PAINT_MS = 80  # the window's first paint, under the card, before it fades
FADE_MS = 180
LOGO_SIZE = 130
# Where things sit, from the card's middle (it was laid out 420x300).
LOGO_MIDDLE, TITLE_TOP, VERSION_TOP, BAR_TOP, MESSAGE_TOP = -55, 18, 52, 84, 96

_running: list[QVariantAnimation] = []  # kept until they finish


def application() -> QApplication:
    """The one QApplication (made here if the loading screen comes first)."""
    if sys.platform == "win32":
        # Own taskbar entry and icon, rather than grouping under python.exe.
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("COCFARM.App")
        except (AttributeError, OSError):
            pass
    return QApplication.instance() or QApplication(sys.argv[:1])


class _Splash(QWidget):
    """The whole screen, see-through and click-through, with the card in
    the middle: one window from start to finish, so the card can grow into
    COCFARM's without another window taking over (which flickers)."""

    def __init__(self, screen) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)  # Tool: no taskbar entry
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setScreen(screen)
        self.setGeometry(screen.availableGeometry())
        self.start = QRectF((self.width() - WIDTH) / 2, (self.height() - HEIGHT) / 2, WIDTH, HEIGHT)
        self.end = self.start
        self.text = ""
        self.logo = QPixmap(str(LOGO))
        self.grow = self.fade = 0.0
        self.asking = False  # a question on the card (``ask``): its own layout

    def set_grow(self, t: float) -> None:
        self.grow = t
        self.update()

    def set_fade(self, t: float) -> None:
        self.fade = t
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        t = self.grow
        a, b = self.start, self.end
        card = QRectF(a.left() + (b.left() - a.left()) * t, a.top() + (b.top() - a.top()) * t,
                      a.width() + (b.width() - a.width()) * t, a.height() + (b.height() - a.height()) * t)
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(1 - self.fade)
        path = QPainterPath()
        radius = RADIUS + (WINDOW_RADIUS - RADIUS) * t
        path.addRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.fillPath(path, BACKGROUND)
        p.setPen(BORDER)
        p.drawPath(path)
        # What's on it: centred, fading as the logo grows.
        x, middle, width = card.left(), card.center().y(), card.width()
        p.setClipPath(path)
        p.setOpacity(p.opacity() * (1 - t))
        if self.asking:  # the logo smaller at the top, the name under it; the question's widgets below
            top, centre = card.top(), card.center().x()
            if not self.logo.isNull():
                p.drawPixmap(QRectF(centre - ASK_LOGO / 2, top + ASK_LOGO_TOP, ASK_LOGO, ASK_LOGO),
                             self.logo, QRectF(self.logo.rect()))
            p.setPen(TEXT)
            p.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
            p.drawText(QRectF(x, top + ASK_TITLE_TOP, width, 34), Qt.AlignmentFlag.AlignCenter, "COCFARM")
            p.setPen(FAINT)
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(x, top + ASK_VERSION_TOP, width, 20), Qt.AlignmentFlag.AlignCenter,
                       f"Version {__version__}")
            p.end()
            return
        if not self.logo.isNull():
            size = LOGO_SIZE * (1 + (GROW - 1) * t)
            p.drawPixmap(QRectF(card.center().x() - size / 2, middle + LOGO_MIDDLE - size / 2, size, size),
                         self.logo, QRectF(self.logo.rect()))
        p.setPen(TEXT)
        p.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        p.drawText(QRectF(x, middle + TITLE_TOP, width, 36), Qt.AlignmentFlag.AlignCenter, "COCFARM")
        p.setPen(FAINT)
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(x, middle + VERSION_TOP, width, 20), Qt.AlignmentFlag.AlignCenter, f"Version {__version__}")
        p.fillRect(QRectF(card.center().x() - 40, middle + BAR_TOP, 80, 3), ACCENT)
        if self.text:
            p.setFont(QApplication.font())
            p.drawText(QRectF(x, middle + MESSAGE_TOP, width, 20), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


_splash: _Splash | None = None


def show() -> QWidget | None:
    """Show the loading screen (once; later calls return the same one)."""
    global _splash
    if _splash is None:
        screen = application().primaryScreen()
        if screen is None:
            return None
        _splash = _Splash(screen)
        _splash.show()
        message("Loading…")
    return _splash


def message(text: str) -> None:
    """Say what's loading, under the logo."""
    if _splash is not None:
        _splash.text = text
        _splash.repaint()
        QApplication.processEvents()


# Asking (``ask``): the card grows to this, its logo smaller at the top, the
# question and its buttons under the name.
ASK_WIDTH, ASK_HEIGHT = 480, 380
ASK_LOGO, ASK_LOGO_TOP, ASK_TITLE_TOP, ASK_VERSION_TOP, ASK_BODY_TOP = 84, 22, 112, 146, 180
ASK_MARGIN = 28
_BUTTON = ("QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 5px;"
           " padding: 7px 18px; font: 10pt 'Segoe UI'; }} QPushButton:hover {{ background: {hover}; }}"
           " QPushButton:focus {{ border: 1px solid #ffffff; }}")


def ask(text: str, buttons: list[str], detail: str = "") -> int | None:
    """Ask on the loading card (it takes clicks meanwhile): ``text`` and a
    faint ``detail`` under it, one button per entry of ``buttons``, the
    first the main one (Enter). Returns the index pressed, or None when the
    card isn't showing (the caller asks some other way)."""
    from PySide6.QtGui import QRegion
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

    splash = _splash
    if splash is None:
        return None
    centre = splash.start.center()
    card = QRectF(centre.x() - ASK_WIDTH / 2, centre.y() - ASK_HEIGHT / 2, ASK_WIDTH, ASK_HEIGHT)
    kept = splash.start
    splash.start = splash.end = card
    splash.asking = True
    panel = QWidget(splash)
    panel.setGeometry(round(card.left()) + ASK_MARGIN, round(card.top()) + ASK_BODY_TOP,
                      round(card.width()) - 2 * ASK_MARGIN, round(card.height()) - ASK_BODY_TOP - ASK_MARGIN)
    rows = QVBoxLayout(panel)
    rows.setContentsMargins(0, 0, 0, 0)
    rows.setSpacing(10)
    for words, colour, size in ((text, TEXT, 10), (detail, FAINT, 9)):
        if not words:
            continue
        label = QLabel(words, panel)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(f"color: {colour.name()}; font: {size}pt 'Segoe UI'; background: transparent;")
        rows.addWidget(label)
    rows.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    chosen: list[int] = []
    loop = QEventLoop()
    for i, words in enumerate(buttons):
        button = QPushButton(words, panel)
        main = i == 0
        button.setStyleSheet(_BUTTON.format(bg=ACCENT.name() if main else "#2d2d2d", fg="#ffffff",
                                            border=ACCENT.name() if main else BORDER.name(),
                                            hover="#6aacff" if main else "#383838"))
        button.setDefault(main)
        button.setAutoDefault(True)
        button.clicked.connect(lambda _=False, n=i: (chosen.append(n), loop.quit()))
        row.addWidget(button)
        if main:
            first = button
    row.addStretch(1)
    rows.addLayout(row)
    # Clicks reach the card (and only the card: the rest of the screen stays usable).
    splash.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
    splash.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
    splash.setMask(QRegion(card.toAlignedRect()))
    panel.show()
    splash.show()
    splash.raise_()
    splash.activateWindow()
    first.setFocus()
    splash.update()
    loop.exec()
    panel.hide()
    panel.deleteLater()
    splash.clearMask()
    splash.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    splash.asking = False
    splash.start = splash.end = kept
    splash.show()
    splash.repaint()
    QApplication.processEvents()
    return chosen[0] if chosen else None


def _animate(duration: int, curve: QEasingCurve.Type, step, done=None) -> None:
    anim = QVariantAnimation()
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(step)

    def finished() -> None:
        if done:
            done()
        _running.remove(anim)

    anim.finished.connect(finished)
    _running.append(anim)
    anim.start()


def _centre(window, screen) -> None:
    """Put ``window`` in the middle of ``screen`` (where the loading screen
    was), not wherever Windows would open it; shrunk to fit a small screen."""
    if screen is None:
        return
    area = screen.availableGeometry()
    window.resize(min(window.width(), area.width()), min(window.height(), area.height()))
    shown = window.geometry()  # what's on screen: the window has no frame (Qt's frameGeometry() is off for it)
    shown.moveCenter(area.center())
    window.setGeometry(shown)


def close() -> None:
    """Leave the loading screen without a window (the program is ending)."""
    global _splash
    splash, _splash = _splash, None
    if splash is not None:
        splash.close()


LIGHT_BACKGROUND = QColor("#f3f3f3")  # the window's light theme
LIGHT_FAINT = QColor("#606060")
PULSE = 0.09  # the logo grows and shrinks by this much while it loads
PULSE_S = 1.2  # one breath, in seconds
FRAME_S = 1 / 40
EVENTS_S = 0.5  # while it loads, Windows' messages are handled this often
REVEAL_GROW = 5.0  # loaded: the logo grows to this many times its size as the window shows through
REVEAL_MS = 450


class Overlay(QWidget):
    """A window covered while another farm's window is built: the logo in
    the middle, breathing. The build holds the window's thread, so it calls
    :meth:`tick` as it goes to keep the logo moving. :meth:`reveal` then
    grows the logo while the cover fades, showing the window under it."""

    def __init__(self, window: QWidget, dark: bool, text: str = "", scale: float = 1.0) -> None:
        super().__init__(window)
        self.dark, self.text, self.base = dark, text, scale
        self.logo = QPixmap(str(LOGO))
        self.started = time.monotonic()
        self.last_frame = self.last_events = 0.0
        self.revealing = 0.0  # 0: loading (breathing); up to 1: fully shown through
        # Covers it all while loading: nothing under it is drawn again for each frame.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setGeometry(window.rect())
        window.installEventFilter(self)  # follows the window's size (maximized as it shows)
        self.timer = QTimer(self, interval=16, timeout=self.update)  # breathes between ticks too
        self.timer.start()
        self.raise_()
        self.show()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def scale(self) -> float:
        """The logo's size now, as a share of LOGO_SIZE."""
        if self.revealing:
            return self.base
        breath = math.sin(2 * math.pi * (time.monotonic() - self.started) / PULSE_S)
        return self.base * (1 + PULSE * breath)

    def tick(self) -> None:
        """Draw the next frame, if it's time: called while the window is built."""
        now = time.monotonic()
        if now - self.last_frame < FRAME_S:
            return
        self.last_frame = now
        self.repaint()  # just the cover, at once: handling every waiting event would slow the build
        if now - self.last_events >= EVENTS_S:  # so Windows doesn't call COCFARM "Not responding"
            self.last_events = now
            # Not the mouse or keyboard: a click now would reach a half-made page.
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def reveal(self) -> None:
        """Grow the logo away and fade the cover, showing the window."""
        self.timer.stop()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # the window is usable at once
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)  # see-through as it fades
        self.base = self.scale()
        self.revealing = 1e-6

        def step(t: float) -> None:
            self.revealing = max(t, 1e-6)
            self.update()

        def done() -> None:
            self.hide()
            self.deleteLater()

        _animate(REVEAL_MS, QEasingCurve.Type.InOutCubic, step, done)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        t = self.revealing
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(1 - t)
        p.fillRect(self.rect(), BACKGROUND if self.dark else LIGHT_BACKGROUND)
        middle = self.rect().center()
        if not self.logo.isNull():
            size = LOGO_SIZE * self.scale() * (1 + (REVEAL_GROW - 1) * t)
            p.setOpacity(1 - t * t)  # the logo stays a moment longer than the cover
            p.drawPixmap(QRectF(middle.x() - size / 2, middle.y() - size / 2 - 20, size, size),
                         self.logo, QRectF(self.logo.rect()))
        if self.text and not t:
            p.setOpacity(1)
            p.setPen(FAINT if self.dark else LIGHT_FAINT)
            p.setFont(QApplication.font())
            p.drawText(QRectF(0, middle.y() + LOGO_SIZE / 2 + 10, self.width(), 24),
                       Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


def finish(window) -> None:
    """Show ``window`` and leave the loading screen: the card grows into
    the window, which is then shown under it, and fades away."""
    global _splash
    splash, _splash = _splash, None
    if splash is None:
        _centre(window, QApplication.primaryScreen())
        window.show()
        return
    # Shown unseen first: its first show takes a moment, lays it out and
    # settles its size, which the card then grows to.
    window.setWindowOpacity(0.0)
    window.show()
    QApplication.processEvents()
    _centre(window, splash.screen())
    QApplication.processEvents()
    splash.end = QRectF(window.geometry().translated(-splash.geometry().topLeft()))

    def grown() -> None:
        window.setWindowOpacity(1.0)  # under the card (it stays on top), which covers it now

        def gone() -> None:
            splash.close()
            splash.deleteLater()

        QTimer.singleShot(PAINT_MS, lambda: _animate(FADE_MS, QEasingCurve.Type.OutQuad, splash.set_fade, gone))

    _animate(GROW_MS, QEasingCurve.Type.OutCubic, splash.set_grow, grown)
