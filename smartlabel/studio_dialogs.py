"""Themed notifications and confirmations; native file/color pickers stay native.

Small, explicit tkinter-compatible surface used by SmartLabel. Confirmations never
accept on Escape/window close; long help and errors scroll inside a bounded dialog.
"""
import tkinter as tk
import customtkinter as ctk

from .ui_layout import (setup_dialog, dialog_header, dialog_footer, wrapped_label,
                        SURFACE, MUTED)


class MessageDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, message, *, kind="info", choices=None, cancel="ok", detail=""):
        super().__init__(parent, fg_color=SURFACE)
        self.result = cancel
        self.title(title)
        self.cancel_value = cancel
        colors = {"info": "#68d7c0", "warning": "#f0bf72", "error": "#f499a5", "question": "#8ccce9"}
        footer = dialog_footer(self)
        self.buttons = {}
        choices = choices or [("ok", "Đã hiểu")]
        for value, caption in reversed(choices):
            button = ctk.CTkButton(footer, text=caption, width=110, height=36, corner_radius=8,
                font=("Segoe UI", 13), fg_color="#294153" if value == cancel else "#256481",
                command=lambda v=value: self.finish(v))
            button.pack(side="right", padx=(8, 0))
            button.bind("<Return>", lambda _event, v=value: self.finish(v))
            self.buttons[value] = button
        dialog_header(self, title)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 14))
        card = ctk.CTkFrame(body, fg_color="#142333", corner_radius=12, border_width=1,
                            border_color=colors.get(kind, colors["info"]))
        card.pack(fill="x")
        wrapped_label(card, str(message)).pack(fill="x", padx=18, pady=16)
        if detail:
            wrapped_label(body, str(detail), color=MUTED).pack(fill="x", padx=16, pady=10)
        setup_dialog(self, parent, 660, min(650, max(300, 240 + len(str(message)) // 4)), close=self.cancel)

    def finish(self, value):
        self.result = value
        self.destroy()

    def cancel(self):
        self.finish(self.cancel_value)


def _show(title, message, *, kind="info", choices=None, cancel="ok", **options):
    parent = options.get("parent") or tk._default_root
    if parent is None:
        raise RuntimeError("SmartLabel dialog requires an application window")
    dialog = MessageDialog(parent, title or "SmartLabel", message or "", kind=kind,
                           choices=choices, cancel=cancel, detail=options.get("detail", ""))
    parent.wait_window(dialog)
    return dialog.result


def showinfo(title=None, message=None, **options):
    return _show(title, message, **options)


def showwarning(title=None, message=None, **options):
    return _show(title, message, kind="warning", **options)


def showerror(title=None, message=None, **options):
    return _show(title, message, kind="error", **options)


def askyesno(title=None, message=None, **options):
    return _show(title, message, kind="question", choices=[(True, "Có"), (False, "Không")], cancel=False, **options)


def askyesnocancel(title=None, message=None, **options):
    return _show(title, message, kind="question", choices=[(True, "Có"), (False, "Không"), (None, "Hủy")], cancel=None, **options)


def askokcancel(title=None, message=None, **options):
    return _show(title, message, kind="question", choices=[(True, "Xác nhận"), (False, "Hủy")], cancel=False, **options)


def askretrycancel(title=None, message=None, **options):
    return _show(title, message, kind="warning", choices=[(True, "Thử lại"), (False, "Hủy")], cancel=False, **options)


def askquestion(title=None, message=None, **options):
    return "yes" if askyesno(title, message, **options) else "no"


class InputDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, prompt, *, number=False, initialvalue=None,
                 minvalue=None, maxvalue=None, show=None):
        super().__init__(parent, fg_color=SURFACE)
        self.result = None
        self.number, self.minimum, self.maximum = number, minvalue, maxvalue
        self.title(title)
        footer = dialog_footer(self)
        ctk.CTkButton(footer, text="Hủy", width=110, height=36, fg_color="#294153", command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(footer, text="Xác nhận", width=110, height=36, command=self.accept).pack(side="right")
        dialog_header(self, title)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        wrapped_label(body, prompt, color=MUTED).pack(fill="x", padx=6, pady=(0, 10))
        self.entry = ctk.CTkEntry(body, height=38, show=show or "")
        self.entry.pack(fill="x", padx=6)
        if initialvalue is not None:
            self.entry.insert(0, str(initialvalue))
        self.error = wrapped_label(body, "", color="#f499a5")
        self.error.pack(fill="x", padx=6, pady=8)
        self.bind("<Return>", lambda _event: self.accept())
        setup_dialog(self, parent, 620, 350)
        self.after(40, self.entry.focus_set)

    def accept(self):
        value = self.entry.get()
        if self.number:
            try:
                value = int(value)
                if self.minimum is not None and value < self.minimum:
                    raise ValueError(f"Giá trị nhỏ nhất là {self.minimum}.")
                if self.maximum is not None and value > self.maximum:
                    raise ValueError(f"Giá trị lớn nhất là {self.maximum}.")
            except ValueError as error:
                self.error.configure(text=str(error) if str(error).startswith("Giá trị") else "Hãy nhập một số nguyên hợp lệ.")
                return
        self.result = value
        self.destroy()


def _ask(title, prompt, number, **options):
    parent = options.pop("parent", None) or tk._default_root
    dialog = InputDialog(parent, title, prompt, number=number, **options)
    parent.wait_window(dialog)
    return dialog.result


def askstring(title, prompt, **options):
    return _ask(title, prompt, False, **options)


def askinteger(title, prompt, **options):
    return _ask(title, prompt, True, **options)
