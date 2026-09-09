"""Small pack helper: a hidden widget cannot be used as a Tk `before` anchor."""
import logging


logger = logging.getLogger(__name__)


def center_dialog(dialog, parent, width=1100, height=760):
    """Fit CTk logical dimensions inside the work area, including Windows DPI."""
    import sys
    left, top, right, bottom = 0, 0, dialog.winfo_screenwidth(), dialog.winfo_screenheight() - 48
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    scale = dialog._get_window_scaling()
    physical_width = min(round(width * scale), right - left - 32)
    physical_height = min(round(height * scale), bottom - top - 64)
    x = max(left + 16, min(parent.winfo_rootx() + (parent.winfo_width() - physical_width) // 2,
                          right - physical_width - 16))
    y = max(top + 32, min(parent.winfo_rooty() + (parent.winfo_height() - physical_height) // 2,
                         bottom - physical_height - 32))
    logical_width, logical_height = int(physical_width / scale), int(physical_height / scale)
    dialog.minsize(min(800, logical_width), min(500, logical_height))
    dialog.geometry(f"{logical_width}x{logical_height}+{x}+{y}")


def pack_before(widget, anchor=None, **options):
    if anchor is not None and anchor.master == widget.master and anchor.winfo_manager() == "pack":
        options["before"] = anchor
    elif anchor is not None:
        logger.warning("Layout anchor is not packed in the same container; appending %s", widget)
    widget.pack(**options)
