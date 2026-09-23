"""Hydro-only dropdown; general/localization controls retain CTk's native menu.

Preserves CTkOptionMenu's variable/callback API and modal ownership. The popup
uses spaced, rounded rows rather than the previous desktop Listbox selection bar.
"""
import tkinter as tk
from tkinter import font as tkfont
import customtkinter as ctk

from .ui_layout import SURFACE, INPUT, PANEL, BORDER, TEXT, MUTED, _work_area


class StudioOptionMenu(ctk.CTkOptionMenu):
    def __init__(self, master, **kwargs):
        self.popup = None
        defaults = dict(fg_color=INPUT, button_color=INPUT, button_hover_color="#243c4e",
                        text_color=TEXT, text_color_disabled=MUTED, corner_radius=8,
                        height=34, font=("Segoe UI", 13), dynamic_resizing=False)
        defaults.update(kwargs)
        super().__init__(master, **defaults)
        self._canvas.configure(takefocus=1)
        for sequence in ("<space>", "<Return>", "<Down>"):
            self._canvas.bind(sequence, self._open_from_key)
        self.bind("<Unmap>", lambda _e: self.close_popup(), add="+")

    def _open_from_key(self, _event):
        self._open_dropdown_menu()
        return "break"

    def _open_dropdown_menu(self):
        if self.cget("state") == "disabled" or not self._values or not self.winfo_viewable():
            return
        if self.popup is not None:
            self.close_popup()
            return
        self.popup = _DropdownPopup(self, list(self._values))

    def close_popup(self):
        if self.popup is not None:
            self.popup.close()

    def configure(self, require_redraw=False, **kwargs):
        if any(key in kwargs for key in ("values", "state", "variable")):
            self.close_popup()
        super().configure(require_redraw=require_redraw, **kwargs)

    def set(self, value):
        self.close_popup()
        super().set(value)

    def _variable_callback(self, *args):
        self.close_popup()
        super()._variable_callback(*args)

    def destroy(self):
        self.close_popup()
        super().destroy()


class _DropdownPopup(tk.Toplevel):
    def __init__(self, menu, values):
        self.menu, self.values = menu, values
        self.owner = menu.winfo_toplevel()
        self.previous_grab = menu.grab_current()
        self.closed = False
        self.bindings = []
        self._content_size = None
        self._scroll_timer = None
        super().__init__(self.owner, bg=SURFACE, takefocus=1)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(self.owner)
        scale = menu._get_widget_scaling()
        font = tkfont.Font(family="Segoe UI", size=-round(13 * scale))
        inset = max(8, round(8 * scale))
        left, top, right, bottom = _work_area(menu, self.owner)
        width = min(right - left - 24, max(menu.winfo_width(),
                    min(round(680 * scale), max(font.measure(v) for v in values) + inset * 3 + 24)))
        panel = ctk.CTkFrame(self, fg_color=SURFACE, bg_color=SURFACE,
                             border_width=1, border_color=BORDER, corner_radius=10)
        panel.pack(fill="both", expand=True)
        self.rows = []
        self.row_heights = []
        self.selected = values.index(menu.get()) if menu.get() in values else 0
        # Local canvas, not CTkScrollableFrame: opening a menu must not install
        # bind_all wheel handlers that linger after it is destroyed.
        viewport = ctk.CTkFrame(panel, fg_color=SURFACE, corner_radius=0)
        viewport.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas = tk.Canvas(viewport, bg=SURFACE, highlightthickness=0, borderwidth=0)
        scrollbar = ctk.CTkScrollbar(viewport, command=self.canvas.yview, width=12,
            fg_color=SURFACE, button_color=BORDER, button_hover_color="#48738e")
        scrollbar.pack(side="right", fill="y", padx=(6, 0))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll_area = tk.Frame(self.canvas, bg=SURFACE, borderwidth=0, highlightthickness=0)
        window_id = self.canvas.create_window(0, 0, window=self.scroll_area, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window_id, width=e.width))
        tk.Misc.bind(self.scroll_area, "<Configure>", self.layout_rows, add="+")
        # Long names wrap rather than being cut or requiring sideways scrolling.
        text_width = max(80, width - inset * 4 - round(30 * scale))
        for index, value in enumerate(values):
            line_width, lines = 0, 1
            for word in value.split():
                measured = font.measure(word + " ")
                if line_width and line_width + measured > text_width:
                    lines += 1
                    line_width = 0
                lines += max(0, (measured - 1) // text_width)
                line_width += measured % text_width
            row_height = max(34, round((lines * font.metrics("linespace")) / scale) + 16)
            button = ctk.CTkButton(self.scroll_area, text=value, width=1, height=row_height,
                anchor="w", font=("Segoe UI", 13), corner_radius=7, border_width=1,
                fg_color=PANEL, hover_color="#233f51", border_color=PANEL, text_color=TEXT,
                command=lambda i=index: self.choose(i))
            button._text_label.configure(wraplength=text_width, justify="left")
            button.pack(fill="x", pady=2)
            button.bind("<MouseWheel>", self.scroll)
            self.rows.append(button)
            self.row_heights.append(round((row_height + 4) * scale))
        self.index = self.selected
        self.select(self.index)
        height = min(bottom - top - 24, round(360 * scale), sum(self.row_heights) + inset * 2 + 8)
        x = max(left + 8, min(menu.winfo_rootx(), right - width - 8))
        y = menu.winfo_rooty() + menu.winfo_height() + 5
        if y + height > bottom - 8:
            y = menu.winfo_rooty() - height - 5
        y = max(top + 8, min(y, bottom - height - 8))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Tab>", self.tab_out)
        self.bind("<Return>", self.commit)
        self.bind("<space>", self.commit)
        self.bind("<Down>", lambda _e: self.move(1))
        self.bind("<Up>", lambda _e: self.move(-1))
        self.bind("<Home>", lambda _e: self.select(0))
        self.bind("<End>", lambda _e: self.select(len(values) - 1))
        self.bind("<Next>", lambda _e: self.move(8))
        self.bind("<Prior>", lambda _e: self.move(-8))
        self.bind("<MouseWheel>", self.scroll)
        self.bind("<ButtonPress-1>", self.outside)
        self.bind("<FocusOut>", self.focus_out)
        self.bind("<Destroy>", self.destroyed, add="+")
        for event in ("<Configure>", "<Unmap>"):
            token = self.owner.bind(event, self.owner_changed, add="+")
            self.bindings.append((event, token))
        self.deiconify()
        self.lift()
        self.grab_set()  # Local only, never grab_set_global().
        self.focus_set()
        if self._scroll_timer is None:
            self._scroll_timer = self.after_idle(self.finish_layout)

    def select(self, index):
        self.index = max(0, min(index, len(self.values) - 1))
        for i, row in enumerate(self.rows):
            row.configure(fg_color="#153d4c" if i == self.selected else PANEL,
                          border_color="#58b8d7" if i == self.index else PANEL)
        self.ensure_visible()
        return "break"

    def layout_rows(self, event):
        size = (event.width, event.height)
        if size == self._content_size:
            return  # Scrolling moves the inner window; it does not resize it.
        self._content_size = size
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self._scroll_timer:
            self.after_cancel(self._scroll_timer)
        self._scroll_timer = self.after_idle(self.finish_layout)

    def finish_layout(self):
        self._scroll_timer = None
        if not self.closed:
            self.ensure_visible()

    def ensure_visible(self):
        canvas = self.canvas
        if not self.rows or self.rows[self.index].winfo_height() <= 1:
            return
        if self.index == 0:
            canvas.yview_moveto(0)
            return
        total = self.scroll_area.winfo_height()
        row = self.rows[self.index]
        row_top = row.winfo_y()
        row_bottom = row_top + row.winfo_height() + 2
        start, end = canvas.yview()
        if row_top < start * total:
            canvas.yview_moveto(row_top / total)
        elif row_bottom > end * total:
            canvas.yview_moveto(max(0, row_bottom - canvas.winfo_height()) / total)

    def move(self, delta):
        return self.select(self.index + delta)

    def choose(self, index):
        self.index = index
        self.commit()

    def scroll(self, event):
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"  # Do not also scroll the form beneath the menu.

    def commit(self, event=None):
        if event is not None and hasattr(event, "x_root") and event.type == tk.EventType.ButtonRelease:
            if not self.contains(event.x_root, event.y_root):
                return "break"
        value = self.values[self.index]
        self.close()
        if value is not None and self.menu.winfo_exists() and self.menu.cget("state") != "disabled":
            self.menu._dropdown_callback(value)
        return "break"

    def contains(self, x, y):
        return (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())

    def outside(self, event):
        if not self.contains(event.x_root, event.y_root):
            self.close()
            return "break"

    def tab_out(self, _event):
        next_widget = self.menu._canvas.tk_focusNext()
        self.close()
        if next_widget is not None:
            next_widget.focus_set()
        return "break"

    def focus_out(self, _event):
        # Application deactivation must not leave an invisible mouse grab behind.
        target = self.focus_get()
        if target is None or target.winfo_toplevel() is not self:
            self.close(restore_focus=False)

    def owner_changed(self, event):
        if event.widget is self.owner:
            self.close(restore_focus=False)

    def destroyed(self, event):
        if event.widget is self:
            self.close(destroy=False, restore_focus=False)

    def close(self, *, destroy=True, restore_focus=True):
        if self.closed:
            return
        self.closed = True
        self.menu.popup = None
        if self._scroll_timer:
            self.after_cancel(self._scroll_timer)
            self._scroll_timer = None
        for event, token in self.bindings:
            if self.owner.winfo_exists():
                # Python 3.10's unbind(sequence, funcid) clears ALL callbacks for
                # the sequence, including CTk's own resize handler. Remove only
                # the Tcl line registered by this popup and retain other binds.
                script = self.owner.bind(event)
                prefix = 'if {"[' + token + ' '
                remaining = "\n".join(line for line in script.split("\n") if not line.startswith(prefix)).rstrip("\n")
                if remaining:
                    remaining += "\n"
                self.owner.tk.call("bind", self.owner._w, event, remaining)
                self.owner.deletecommand(token)
        try:
            if self.grab_current() is self:
                self.grab_release()
            if (self.grab_current() is None and self.previous_grab is not None
                    and self.previous_grab.winfo_exists() and self.previous_grab.winfo_viewable()):
                self.previous_grab.grab_set()
            if restore_focus and self.menu.winfo_viewable():
                self.menu._canvas.focus_set()
        except tk.TclError:
            pass
        if destroy:
            self.destroy()
