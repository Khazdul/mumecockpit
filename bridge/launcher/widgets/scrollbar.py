"""Reusable click-to-jump scrollbar widget for prompt_toolkit applications.

A leaf module: depends only on prompt_toolkit. Application-agnostic — it
holds no reference to any specific frame or container, and is reusable
across the statistics frame, launcher run-browser, and other future
scrollable surfaces.
"""

from __future__ import annotations

from typing import Callable

try:
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.mouse_events import MouseEventType
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    raise


_DEFAULT_THUMB_STYLE = "bold fg:#ffffff"
_DEFAULT_TRACK_STYLE = "fg:#585858"

_THUMB_GLYPH = "█"   # █
_TRACK_GLYPH = "░"   # ░


class Scrollbar:
    def __init__(
        self,
        total_items: int,
        visible_items: int,
        height: int,
        on_change: Callable[[int], None] | None = None,
        thumb_style: str = _DEFAULT_THUMB_STYLE,
        track_style: str = _DEFAULT_TRACK_STYLE,
    ):
        self._total       = max(0, int(total_items))
        self._visible     = max(0, int(visible_items))
        self._height      = max(1, int(height))
        self._on_change   = on_change
        self._thumb_style = thumb_style
        self._track_style = track_style
        self._offset      = 0

    # ------------------------------------------------------------------
    # Public read-only state
    # ------------------------------------------------------------------
    @property
    def scroll_offset(self) -> int:
        return self._offset

    @property
    def visible(self) -> bool:
        return self._total > self._visible

    # ------------------------------------------------------------------
    # Reconfiguration / scrolling
    # ------------------------------------------------------------------
    def update(self, total_items: int, visible_items: int) -> None:
        self._total   = max(0, int(total_items))
        self._visible = max(0, int(visible_items))
        max_scroll = self._max_scroll()
        if self._offset > max_scroll:
            self._offset = max_scroll

    def scroll_to(self, offset: int) -> None:
        new_offset = max(0, min(self._max_scroll(), int(offset)))
        if new_offset != self._offset:
            self._offset = new_offset
            if self._on_change:
                self._on_change(new_offset)

    def scroll_by(self, delta: int) -> None:
        self.scroll_to(self._offset + int(delta))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(self) -> StyleAndTextTuples:
        frags: StyleAndTextTuples = []

        if not self.visible:
            for i in range(self._height):
                frags.append((self._track_style, " "))
                if i < self._height - 1:
                    frags.append(("", "\n"))
            return frags

        thumb_top, thumb_h = self._thumb_geometry()

        for i in range(self._height):
            if thumb_top <= i < thumb_top + thumb_h:
                style = self._thumb_style
                ch    = _THUMB_GLYPH
            else:
                style = self._track_style
                ch    = _TRACK_GLYPH

            def _handler(ev, row=i):
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                self.scroll_to(self._click_to_offset(row))

            frags.append((style, ch, _handler))
            if i < self._height - 1:
                frags.append(("", "\n"))
        return frags

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _max_scroll(self) -> int:
        return max(0, self._total - self._visible)

    def _thumb_geometry(self) -> tuple[int, int]:
        """Return (thumb_top, thumb_height) in cell coordinates."""
        if self._total <= 0:
            return 0, 0
        ratio   = self._visible / self._total
        thumb_h = max(1, round(ratio * self._height))
        thumb_h = min(thumb_h, self._height)

        max_thumb_top = self._height - thumb_h
        max_scroll    = self._max_scroll()
        if max_thumb_top <= 0 or max_scroll <= 0:
            return 0, thumb_h

        thumb_top = round(self._offset / max_scroll * max_thumb_top)
        thumb_top = max(0, min(max_thumb_top, thumb_top))
        return thumb_top, thumb_h

    def _click_to_offset(self, cell_row: int) -> int:
        """Map a click on cell `cell_row` to a scroll offset.

        Centres the thumb on the clicked cell, then maps the resulting
        thumb position back to a scroll offset.
        """
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return 0
        _, thumb_h    = self._thumb_geometry()
        max_thumb_top = self._height - thumb_h
        if max_thumb_top <= 0:
            return 0
        target_top = cell_row - thumb_h // 2
        target_top = max(0, min(max_thumb_top, target_top))
        return round(target_top / max_thumb_top * max_scroll)


# ---------------------------------------------------------------------------
# Smoke demo: `python -m bridge.launcher.widgets.scrollbar`
# 20-item list paired with a 10-row scrollbar. Click the bar to jump.
# UP/DOWN keys also scroll; q or ESC to quit.
# ---------------------------------------------------------------------------
def _demo():
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    items   = [f"Item {i + 1:02d}" for i in range(20)]
    visible = 10
    height  = 10

    sb = Scrollbar(total_items=len(items), visible_items=visible, height=height)

    def list_text():
        off  = sb.scroll_offset
        view = items[off:off + visible]
        out  = []
        for i, item in enumerate(view):
            out.append(("", f"  {item}  "))
            if i < len(view) - 1:
                out.append(("", "\n"))
        return out

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        sb.scroll_by(-1)
        event.app.invalidate()

    @kb.add("down")
    def _(event):
        sb.scroll_by(1)
        event.app.invalidate()

    @kb.add("q")
    @kb.add("c-c")
    @kb.add("escape", eager=True)
    def _(event):
        event.app.exit()

    list_win = Window(
        content=FormattedTextControl(text=list_text, focusable=True),
        width=14, height=height, wrap_lines=False, always_hide_cursor=True,
    )
    bar_win = Window(
        content=FormattedTextControl(text=sb.render, focusable=False),
        width=1, height=height, wrap_lines=False, always_hide_cursor=True,
    )
    hint_win = Window(
        content=FormattedTextControl(
            text=[("fg:#585858", "Click the bar · ↑↓ scroll · q quit")],
            focusable=False,
        ),
        height=1, wrap_lines=False,
    )

    root = HSplit([VSplit([list_win, bar_win]), hint_win])
    app  = Application(
        layout=Layout(root),
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
    )
    sb._on_change = lambda _off: app.invalidate()
    app.run()


if __name__ == "__main__":
    _demo()
