"""Shared dark dropdown with owned, bounded popup and local-grab restoration.

Preserves CTkOptionMenu's variables/callbacks/get/set/configure contract. The list
is rendered by Tk (not hundreds of CTk buttons), so long project lists stay fast.
"""
import tkinter as tk
from tkinter import font as tkfont
import customtkinter as ctk

from .ui_layout import PANEL, BORDER, TEXT, MUTED, _work_area


class StudioOptionMenu(ctk.CTkOptionMenu):
    def __init__(self, master, **kwargs):
        self.popup = None
        defaults = dict(fg_color="#1b3042", button_color="#29475d", button_hover_color="#365d77",
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
        super().__init__(self.owner, bg=BORDER, takefocus=1)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(self.owner)
        scale = menu._get_widget_scaling()
        font = tkfont.Font(family="Segoe UI", size=-round(13 * scale))
        inset = max(8, round(8 * scale))
        left, top, right, bottom = _work_area(menu, self.owner)
        width = min(right - left - 24, max(menu.winfo_width(),
                    min(round(680 * scale), max(font.measure(v) for v in values) + inset * 3 + 24)))
        # Exportselection=False is essential: never disturb the user's copied code.
        panel = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        panel.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(panel, bg=PANEL, fg=TEXT, selectbackground="#28566e",
            selectforeground="#ffffff", activestyle="none", font=font, borderwidth=0,
            highlightthickness=0, exportselection=False, selectmode="browse",
            height=min(9, len(values)), relief="flat")
        scrollbar = ctk.CTkScrollbar(panel, orientation="vertical", command=self.listbox.yview,
                                     fg_color=PANEL, button_color="#355467", button_hover_color="#48738e", width=12)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        if len(values) > 9:
            scrollbar.pack(side="right", fill="y", padx=(0, inset), pady=inset)
        self.listbox.pack(fill="both", expand=True, padx=inset, pady=inset)
        for value in values:
            self.listbox.insert("end", ("✓  " if value == menu.get() else "    ") + value)
        # Particularly long project/benchmark names remain readable, not clipped.
        needs_horizontal = max(font.measure(v) for v in values) + inset * 3 + 24 > width
        if needs_horizontal:
            horizontal = ctk.CTkScrollbar(panel, orientation="horizontal", command=self.listbox.xview,
                                          fg_color=PANEL, button_color="#355467", button_hover_color="#48738e", height=12)
            horizontal.pack(side="bottom", fill="x", padx=inset, pady=(0, inset), before=self.listbox)
            self.listbox.configure(xscrollcommand=horizontal.set)
        index = values.index(menu.get()) if menu.get() in values else 0
        self.select(index)
        height = min(bottom - top - 24, (font.metrics("linespace") + 4) * min(9, len(values))
                     + inset * 2 + (round(20 * scale) if needs_horizontal else 0))
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
        self.listbox.bind("<ButtonRelease-1>", self.commit)
        self.listbox.bind("<Motion>", self.hover)
        self.listbox.bind("<MouseWheel>", self.scroll)
        self.bind("<ButtonPress-1>", self.outside)
        self.bind("<FocusOut>", self.focus_out)
        self.bind("<Destroy>", self.destroyed, add="+")
        for event in ("<Configure>", "<Unmap>"):
            token = self.owner.bind(event, self.owner_changed, add="+")
            self.bindings.append((event, token))
        self.deiconify()
        self.lift()
        self.grab_set()  # Local only, never grab_set_global().
        self.listbox.focus_set()

    def select(self, index):
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)

    def hover(self, event):
        self.select(self.listbox.nearest(event.y))

    def scroll(self, event):
        self.listbox.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"  # Do not also scroll the form beneath the menu.

    def commit(self, event=None):
        if event is not None and hasattr(event, "x_root") and event.type == tk.EventType.ButtonRelease:
            if not self.contains(event.x_root, event.y_root):
                return "break"
        selection = self.listbox.curselection()
        value = self.values[selection[0]] if selection else None
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
