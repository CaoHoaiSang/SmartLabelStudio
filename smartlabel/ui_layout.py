"""Shared desktop layout: owned dialogs, DPI-safe placement and readable controls."""
import logging
import sys
import tkinter as tk

import customtkinter as ctk


logger = logging.getLogger(__name__)


SURFACE = "#0a131c"  # Matches the Hydro whole-image classifier panel.
INPUT = "#05090d"
PANEL = "#142333"
BORDER = "#294153"
TEXT = "#e1edf5"
MUTED = "#9bb0c0"
ACCENT = "#68d7c0"
TITLE = "#22b9ee"


class StudioToplevel(ctk.CTkToplevel):
    """Build an owned window while hidden, then map it once in setup_dialog.

    CTk 5.2's Windows titlebar recoloring withdraws the window and calls update()
    during construction, which can restore focus to the main window afterwards.
    Keep the OS titlebar here; theme the content without that reentrant map cycle.
    """
    _deactivate_windows_window_header_manipulation = True

    def __init__(self, parent, **kwargs):
        kwargs.setdefault("fg_color", SURFACE)
        super().__init__(parent, **kwargs)
        self.withdraw()
        self.transient(parent.winfo_toplevel())


class StudioEntry(ctk.CTkEntry):
    """Black input surface, including rows added after a dialog has opened."""
    def __init__(self, master, **kwargs):
        defaults = dict(fg_color=INPUT, border_color=BORDER, border_width=1,
                        text_color=TEXT, placeholder_text_color=MUTED,
                        corner_radius=8)
        if isinstance(master.winfo_toplevel(), StudioToplevel):
            defaults["height"] = 34
        defaults.update(kwargs)
        super().__init__(master, **defaults)


def dialog_bounds(work_area, owner, width, height, scale=1.0):
    """Return logical size and physical position, including negative monitor origins."""
    left, top, right, bottom = work_area
    scale = max(0.5, float(scale))
    physical_width = max(1, min(round(width * scale), right - left - 32))
    physical_height = max(1, min(round(height * scale), bottom - top - 64))
    ox, oy, ow, oh = owner
    x = max(left + 16, min(ox + (ow - physical_width) // 2, right - physical_width - 16))
    y = max(top + 32, min(oy + (oh - physical_height) // 2, bottom - physical_height - 32))
    return int(physical_width / scale), int(physical_height / scale), x, y


def _work_area(dialog, parent):
    fallback = (0, 0, dialog.winfo_screenwidth(), dialog.winfo_screenheight() - 48)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        api = ctypes.windll.user32
        api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        api.MonitorFromWindow.restype = wintypes.HANDLE
        api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo(); info.size = ctypes.sizeof(info)
        monitor = api.MonitorFromWindow(parent.winfo_id(), 2)
        if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    return fallback


def center_dialog(dialog, parent, width=1100, height=760):
    """Fit CTk logical dimensions in the *owner's monitor* work area, not primary."""
    owner = (parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height())
    if owner[2] <= 1 or owner[3] <= 1:
        area = _work_area(dialog, parent)
        owner = (area[0], area[1], area[2] - area[0], area[3] - area[1])
    w, h, x, y = dialog_bounds(_work_area(dialog, parent), owner, width, height, dialog._get_window_scaling())
    dialog.minsize(min(560, w), min(320, h))
    # Tk's +negative coordinates are absolute (unlike a leading '-' right/bottom offset).
    dialog.geometry(f"{w}x{h}+{x}+{y}")


def setup_dialog(dialog, parent, width, height, *, close=None, modal=True):
    """One lifetime/focus policy. No permanent topmost flag and no orphan mouse grab.

    Call after building content. A delayed lift follows CTk's Windows titlebar reset;
    transient ownership keeps Fleet above its owner without blocking background jobs.
    """
    close = close or dialog.destroy
    dialog.configure(fg_color=SURFACE)
    # Do not repeatedly redraw a visible hierarchy while applying its theme.
    style_dialog_content(dialog)
    dialog.transient(parent.winfo_toplevel())
    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.bind("<Escape>", lambda _event: close())
    previous_grab = dialog.grab_current()
    timers = []
    center_dialog(dialog, parent, width, height)
    if isinstance(dialog, StudioToplevel):
        dialog.deiconify()

    def show():
        if not dialog.winfo_exists() or dialog.state() == "withdrawn":
            return
        current = dialog.grab_current()
        if current is not None and current not in (dialog, parent, previous_grab):
            return  # A newer nested dialog owns focus; do not cover it.
        dialog.lift()
        if modal:
            current = dialog.grab_current()
            if current is None or current in (parent, previous_grab):
                dialog.grab_set()
        dialog.focus_set()

    def lift_owned():
        if (dialog.winfo_exists() and dialog.state() != "withdrawn"
                and dialog.grab_current() in (None, dialog, parent, previous_grab)):
            dialog.lift()

    def cleanup(event):
        if event.widget is not dialog:
            return
        for timer in timers:
            try:
                dialog.after_cancel(timer)
            except tk.TclError:
                pass
        try:
            current = dialog.grab_current()
            if current is dialog:
                dialog.grab_release()
            if modal and previous_grab is not None and previous_grab is not dialog and previous_grab.winfo_exists():
                if dialog.grab_current() is None and previous_grab.winfo_viewable():
                    previous_grab.grab_set()
        except tk.TclError:
            pass

    dialog.bind("<Destroy>", cleanup, add="+")
    timers.extend((dialog.after(10, show), dialog.after(260, lift_owned)))


def style_dialog_content(parent):
    """Apply desktop typography to dialog controls, not the main workspace/canvas."""
    for widget in parent.winfo_children():
        if isinstance(widget, ctk.CTkScrollableFrame):
            # CTkScrollableFrame owns a separate Tk canvas. Styling its outer
            # CTkFrame alone leaves a gray rectangle behind the content.
            if widget.cget("fg_color") != SURFACE:
                widget.configure(fg_color=SURFACE)
        if isinstance(widget, (ctk.CTkLabel, ctk.CTkButton, ctk.CTkEntry, ctk.CTkCheckBox, ctk.CTkOptionMenu)):
            font = widget.cget("font")
            if isinstance(font, ctk.CTkFont):
                family, size, weight = font.cget("family"), font.cget("size"), font.cget("weight")
            else:
                family, size = font[:2]
                weight = font[2] if len(font) > 2 else "normal"
            options = {}
            desired_family = "Segoe UI Semibold" if "Semibold" in family else "Segoe UI"
            if family != "Consolas" and (family != desired_family or size < 13):
                options["font"] = (desired_family, max(13, size), weight)
            if isinstance(widget, (ctk.CTkButton, ctk.CTkEntry, ctk.CTkOptionMenu)):
                if widget.cget("height") < 34:
                    options["height"] = 34
                if widget.cget("corner_radius") != 8:
                    options["corner_radius"] = 8
            if isinstance(widget, ctk.CTkEntry):
                for key, value in (("fg_color", INPUT), ("border_color", BORDER), ("border_width", 1)):
                    if widget.cget(key) != value:
                        options[key] = value
            if options:
                widget.configure(**options)
            if isinstance(widget, ctk.CTkLabel) and widget.cget("wraplength"):
                _fit_label(widget)
        if isinstance(widget, ctk.CTkFrame) and widget.cget("fg_color") in (ctk.ThemeManager.theme["CTkFrame"]["fg_color"], ctk.ThemeManager.theme["CTkFrame"]["top_fg_color"]):
            widget.configure(fg_color=SURFACE, corner_radius=12)
        style_dialog_content(widget)


def dialog_header(parent, title, subtitle=""):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="x", padx=20, pady=(18, 10))
    wrapped_label(frame, title, size=20, bold=True, color=TITLE).pack(fill="x")
    if subtitle:
        wrapped_label(frame, subtitle, color=MUTED).pack(fill="x", pady=(4, 0))
    return frame


def wrapped_label(parent, text, *, size=13, bold=False, color=TEXT):
    label = ctk.CTkLabel(parent, text=text, anchor="w", justify="left", width=1,
                         font=("Segoe UI", size, "bold" if bold else "normal"), text_color=color,
                         wraplength=400)
    _fit_label(label)
    return label


def _fit_label(label):
    if getattr(label, "_studio_wrap", False):
        return
    label._studio_wrap = True
    def fit(event):
        # Hidden tabs have no final allocation. Wrapping their provisional sizes
        # can cause thousands of layout passes during the first app.update().
        # Refit on Map when the user actually opens that tab/dialog instead.
        if not label.winfo_ismapped():
            return
        # A vertically packed text label MUST consume the available row width.
        # Otherwise wrapping to its own requested width feeds back into pack,
        # repeatedly shrinking a paragraph down to a 100px column.
        if label.winfo_manager() == "pack":
            layout = label.pack_info()
            if layout["side"] in ("top", "bottom") and layout["fill"] not in ("x", "both"):
                label.pack_configure(fill="x")
                label.configure(anchor="w")
                return
            if layout["side"] in ("left", "right") and not layout["expand"]:
                # A content-sized horizontal label has no independent width.
                # Never feed its measured text width back into wraplength.
                return
        allocated = label.winfo_width()
        if allocated <= 1:
            return  # Not allocated yet; never derive wrapping from transient 1px.
        width = max(40, int(allocated / label._get_widget_scaling()) - 4)
        if label.cget("wraplength") != width:
            label.configure(wraplength=width)
    # CTkLabel.bind targets its inner text/canvas; using their width would create
    # a self-shrinking layout loop. Observe the outer Tk frame instead.
    tk.Misc.bind(label, "<Configure>", fit, add="+")
    tk.Misc.bind(label, "<Map>", fit, add="+")


def dialog_section(parent, title, subtitle=""):
    card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
    card.pack(fill="x", pady=(0, 12))
    wrapped_label(card, title, size=15, bold=True, color=TITLE).pack(fill="x", padx=16, pady=(10, 4))
    if subtitle:
        wrapped_label(card, subtitle, color=MUTED).pack(fill="x", padx=16, pady=(0, 8))
    content = ctk.CTkFrame(card, fg_color="transparent")
    content.pack(fill="x", padx=16, pady=(4, 14))
    return content


def dialog_footer(parent):
    footer = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0, height=58)
    footer.pack(side="bottom", fill="x")
    inner = ctk.CTkFrame(footer, fg_color="transparent")
    inner.pack(fill="x", padx=20, pady=12)
    return inner


class SourceTabs(ctk.CTkFrame):
    """A narrow image sidebar cannot fit four text tabs on one line."""
    def __init__(self, master, variable, command):
        super().__init__(master, fg_color="transparent")
        self.variable, self.command = variable, command
        self.grid_columnconfigure((0, 1), weight=1, uniform="sources")
        self.buttons = {}
        for index, (value, caption) in enumerate((("Giàn", "Giàn"), ("Bổ trợ", "Bổ trợ"),
                                                   ("Khách đóng góp", "Khách đóng góp"), ("TEST", "Bộ TEST"))):
            button = ctk.CTkButton(self, text=caption, width=1, height=34, corner_radius=8,
                font=("Segoe UI", 13), border_width=1, command=lambda v=value: command(v))
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
            self.buttons[value] = button
        self._trace = variable.trace_add("write", self._sync)
        self._sync()

    def _sync(self, *_):
        for value, button in self.buttons.items():
            selected = self.variable.get() == value
            button.configure(fg_color="#256481" if selected else PANEL,
                hover_color="#327b9c" if selected else "#223e51",
                border_color="#68b4d5" if selected else BORDER, text_color=TEXT if selected else MUTED)

    def destroy(self):
        self.variable.trace_remove("write", self._trace)
        super().destroy()


class TwoColumnCards(ctk.CTkFrame):
    """Equal-height sibling cards; stack only when there is not enough width."""
    def __init__(self, parent, *, breakpoint=840):
        super().__init__(parent, fg_color="transparent", width=1)
        self.breakpoint = breakpoint
        self.cards = ()
        self.secondary_visible = True
        self.compact = None
        tk.Misc.bind(self, "<Configure>", lambda event: self.reflow(event.width), add="+")

    def set_cards(self, first, second):
        self.cards = (first, second)
        self.reflow()

    def set_secondary_visible(self, visible):
        self.secondary_visible = visible
        self.reflow()

    def reflow(self, width=None):
        if not self.cards:
            return
        compact = (width or self.winfo_width()) / self._get_widget_scaling() < self.breakpoint
        self.compact = compact
        paired = self.secondary_visible and not compact
        self.grid_columnconfigure(0, weight=1, uniform="dataset_tools")
        self.grid_columnconfigure(1, weight=1 if paired else 0, uniform="dataset_tools" if paired else "")
        self.cards[0].grid(row=0, column=0, sticky="nsew", padx=(0, 6 if paired else 0))
        if self.secondary_visible:
            self.cards[1].grid(row=1 if compact else 0, column=0 if compact else 1,
                               sticky="nsew", padx=(6 if paired else 0, 0), pady=(8 if compact else 0, 0))
        else:
            self.cards[1].grid_remove()


def pack_before(widget, anchor=None, **options):
    if anchor is not None and anchor.master == widget.master and anchor.winfo_manager() == "pack":
        options["before"] = anchor
    elif anchor is not None:
        logger.warning("Layout anchor is not packed in the same container; appending %s", widget)
    widget.pack(**options)
