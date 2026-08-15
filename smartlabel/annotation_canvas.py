from __future__ import annotations

import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from .models import Annotation, ImageRecord, Project


class AnnotationCanvas(tk.Canvas):
    """Zoomable image canvas with box/polygon creation and selection."""

    def __init__(self, master, on_change: Callable[[], None], on_select: Callable[[str | None], None], on_prompt: Callable[[float, float, int], None] | None = None, on_view_change: Callable[[float], None] | None = None, **kwargs):
        super().__init__(master, bg="#091119", highlightthickness=0, cursor="crosshair", **kwargs)
        self.on_change = on_change
        self.on_select = on_select
        self.on_prompt = on_prompt
        self.on_view_change = on_view_change
        self.project: Project | None = None
        self.record: ImageRecord | None = None
        self.image: Image.Image | None = None
        self.photo = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.mode = "select"
        self.geometry_mode = "rect"
        self.active_class_id = 0
        self.default_attributes: dict[str, str] = {}
        self.selected_id: str | None = None
        self.drag_start: tuple[float, float] | None = None
        self.preview_item: int | None = None
        self.polygon_points: list[list[float]] = []
        self.prompt_points: list[tuple[float, float, int]] = []
        self.history: list[list[dict]] = []
        self.future: list[list[dict]] = []
        self.pan_start: tuple[float, float] | None = None
        self.pan_origin: tuple[float, float] | None = None
        self.space_pressed = False
        self.edit_state: dict | None = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._double_click)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-3>", lambda _e: self.cancel_action())
        self.bind("<Delete>", lambda _e: self.delete_selected())
        self.bind("<Control-z>", lambda _e: self.undo())
        self.bind("<Control-y>", lambda _e: self.redo())
        self.bind("<KeyPress-space>", self._space_down)
        self.bind("<KeyRelease-space>", self._space_up)
        self.bind("<ButtonPress-2>", self._pan_press)
        self.bind("<B2-Motion>", self._pan_drag)
        self.bind("<ButtonRelease-2>", self._pan_release)

    def load(self, project: Project, record: ImageRecord, image_path: str) -> None:
        self.project = project
        self.record = record
        with Image.open(image_path) as source:
            self.image = source.convert("RGB")
        self.selected_id = None
        self.polygon_points.clear()
        self.prompt_points.clear()
        self.history.clear()
        self.future.clear()
        self.fit_image()

    def clear_image(self) -> None:
        """Reset the canvas after the last image is removed from a project."""
        self.record = None
        self.image = None
        self.photo = None
        self.selected_id = None
        self.polygon_points.clear()
        self.prompt_points.clear()
        self.history.clear()
        self.future.clear()
        self.redraw()
        self._notify_view()

    def checkpoint(self) -> None:
        if not self.record:
            return
        self.history.append([ann.to_dict() for ann in self.record.annotations])
        self.history = self.history[-50:]
        self.future.clear()

    def _restore(self, snapshot: list[dict]) -> None:
        if not self.record:
            return
        self.record.annotations = [Annotation.from_dict(item) for item in snapshot]
        self.selected_id = None
        self.on_select(None)
        self.on_change()
        self.redraw()
        self._notify_view()

    def undo(self) -> None:
        if not self.record or not self.history:
            return
        self.future.append([ann.to_dict() for ann in self.record.annotations])
        self._restore(self.history.pop())

    def redo(self) -> None:
        if not self.record or not self.future:
            return
        self.history.append([ann.to_dict() for ann in self.record.annotations])
        self._restore(self.future.pop())

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.cancel_action()
        self.configure(cursor="crosshair" if mode in {"box", "polygon", "sam_click", "sam_positive", "sam_negative", "orientation"} else "arrow")

    def set_geometry_mode(self, mode: str) -> None:
        if mode not in {"rect", "seg", "obb", "ori"}:
            return
        self.geometry_mode = mode
        self.cancel_action()
        self.redraw()

    def set_default_attributes(self, values: dict[str, str]) -> None:
        """Apply explicit project defaults only to annotations created later."""
        self.default_attributes = dict(values)

    def fit_image(self) -> None:
        if not self.image:
            return
        canvas_w = max(self.winfo_width(), 800)
        canvas_h = max(self.winfo_height(), 600)
        self.scale = min((canvas_w - 30) / self.image.width, (canvas_h - 30) / self.image.height)
        self.scale = max(0.05, self.scale)
        self.offset_x = (canvas_w - self.image.width * self.scale) / 2
        self.offset_y = (canvas_h - self.image.height * self.scale) / 2
        self.redraw()
        self._notify_view()

    def center_image(self) -> None:
        if not self.image:
            return
        self.offset_x = (max(self.winfo_width(), 1) - self.image.width * self.scale) / 2
        self.offset_y = (max(self.winfo_height(), 1) - self.image.height * self.scale) / 2
        self.redraw()
        self._notify_view()

    def zoom(self, factor: float) -> None:
        if not self.image:
            return
        center_x = max(self.winfo_width(), 1) / 2
        center_y = max(self.winfo_height(), 1) / 2
        old_scale = self.scale
        self.scale = min(max(self.scale * factor, 0.05), 8.0)
        image_x = (center_x - self.offset_x) / old_scale
        image_y = (center_y - self.offset_y) / old_scale
        self.offset_x = center_x - image_x * self.scale
        self.offset_y = center_y - image_y * self.scale
        self.redraw()
        self._notify_view()

    def _notify_view(self) -> None:
        if self.on_view_change:
            self.on_view_change(self.scale)

    def redraw(self) -> None:
        self.delete("all")
        if not self.image or not self.record:
            self.create_text(self.winfo_width() / 2, self.winfo_height() / 2, text="Chọn hoặc nhập ảnh để bắt đầu", fill="#7f94a8", font=("Segoe UI", 16))
            return
        size = (max(1, round(self.image.width * self.scale)), max(1, round(self.image.height * self.scale)))
        resized = self.image.resize(size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(resized)
        self.create_image(self.offset_x, self.offset_y, image=self.photo, anchor="nw", tags="image")
        for ann in self.record.annotations:
            self._draw_annotation(ann)
        for x, y, label in self.prompt_points:
            cx, cy = self.to_canvas(x, y)
            color = "#43d17d" if label == 1 else "#f26464"
            self.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=color, outline="#ffffff", width=2, tags="prompt")
            self.create_text(cx, cy - 11, text="+" if label == 1 else "−", fill=color, font=("Segoe UI Semibold", 12), tags="prompt")
        if self.polygon_points:
            coords = [coord for point in self.polygon_points for coord in self.to_canvas(*point)]
            if len(coords) >= 4:
                self.create_line(*coords, fill="#ffffff", width=2, dash=(4, 3), tags="preview")

    def _draw_annotation(self, ann: Annotation) -> None:
        if not self.project:
            return
        class_info = self.project.class_by_id(ann.class_id)
        color = class_info.color if class_info else "#21c7ff"
        selected = ann.id == self.selected_id
        width = 4 if selected else 2
        geometry_drawn = "rect"
        if self.geometry_mode == "seg" and len(ann.points) >= 3:
            coords = [coord for point in ann.points for coord in self.to_canvas(*point)]
            self.create_polygon(*coords, outline=color, fill="", width=width, tags=("annotation", ann.id))
            geometry_drawn = "seg"
        elif self.geometry_mode == "obb" and len(ann.obb) == 4:
            coords = [coord for point in ann.obb for coord in self.to_canvas(*point)]
            self.create_polygon(*coords, outline=color, fill="", width=width, tags=("annotation", ann.id))
            geometry_drawn = "obb"
        elif len(ann.bbox) == 4:
            x, y, w, h = ann.bbox
            x1, y1 = self.to_canvas(x, y)
            x2, y2 = self.to_canvas(x + w, y + h)
            dash = () if self.geometry_mode in {"rect", "ori"} else (5, 3)
            self.create_rectangle(x1, y1, x2, y2, outline=color, width=width, dash=dash, tags=("annotation", ann.id))
        if self.geometry_mode == "ori" and len(ann.orientation) == 2:
            (cx, cy), (tx, ty) = ann.orientation
            c1 = self.to_canvas(cx, cy)
            c2 = self.to_canvas(tx, ty)
            self.create_line(*c1, *c2, fill=color, width=width + 1, arrow="last", arrowshape=(14, 17, 6), tags=("annotation", ann.id))
            self.create_oval(c1[0] - 5, c1[1] - 5, c1[0] + 5, c1[1] + 5, fill="#091119", outline=color, width=2, tags=("annotation", ann.id))
            geometry_drawn = "ori"
        if len(ann.bbox) == 4:
            x, y, _w, _h = ann.bbox
            x1, y1 = self.to_canvas(x, y)
            label = class_info.name if class_info else str(ann.class_id)
            if ann.confidence is not None:
                label += f"  {ann.confidence:.2f}"
            label += f" · {geometry_drawn.upper()}"
            self.create_text(x1 + 5, max(y1 - 5, self.offset_y + 12), text=label, fill=color, anchor="sw", font=("Segoe UI Semibold", 10), tags=("annotation", ann.id))
        if selected and self.geometry_mode == "rect" and len(ann.bbox) == 4:
            x, y, w, h = ann.bbox
            x1, y1 = self.to_canvas(x, y)
            x2, y2 = self.to_canvas(x + w, y + h)
            self.create_rectangle(x1 - 3, y1 - 3, x2 + 3, y2 + 3, outline="#eefaff", width=1, dash=(5, 3), tags=("focus", ann.id))
            for _name, hx, hy in self._rect_handles(ann):
                self.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill="#eefaff", outline=color, width=2, tags=("focus", ann.id))

    def _rect_handles(self, ann: Annotation) -> list[tuple[str, float, float]]:
        if len(ann.bbox) != 4:
            return []
        x, y, w, h = ann.bbox
        x1, y1 = self.to_canvas(x, y)
        x2, y2 = self.to_canvas(x + w, y + h)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        return [
            ("nw", x1, y1), ("n", mx, y1), ("ne", x2, y1),
            ("e", x2, my), ("se", x2, y2), ("s", mx, y2),
            ("sw", x1, y2), ("w", x1, my),
        ]

    def _handle_at(self, canvas_x: float, canvas_y: float) -> str | None:
        if self.geometry_mode != "rect" or not self.record or not self.selected_id:
            return None
        ann = next((item for item in self.record.annotations if item.id == self.selected_id), None)
        if not ann:
            return None
        for name, hx, hy in self._rect_handles(ann):
            if abs(canvas_x - hx) <= 9 and abs(canvas_y - hy) <= 9:
                return name
        return None

    def to_image(self, canvas_x: float, canvas_y: float) -> tuple[float, float]:
        if not self.image:
            return 0.0, 0.0
        x = min(max((canvas_x - self.offset_x) / self.scale, 0), self.image.width)
        y = min(max((canvas_y - self.offset_y) / self.scale, 0), self.image.height)
        return x, y

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self.offset_x + x * self.scale, self.offset_y + y * self.scale

    def _press(self, event) -> None:
        self.focus_set()
        if not self.record:
            return
        if self.mode == "select":
            handle = self._handle_at(event.x, event.y)
            if handle and self.selected_id:
                ann = next((item for item in self.record.annotations if item.id == self.selected_id), None)
                if ann:
                    self.checkpoint()
                    self.edit_state = {
                        "id": ann.id, "handle": handle, "start": self.to_image(event.x, event.y),
                        "bbox": list(ann.bbox), "points": [list(p) for p in ann.points],
                        "obb": [list(p) for p in ann.obb], "orientation": [list(p) for p in ann.orientation],
                        "moved": False,
                    }
                    self.configure(cursor="sizing")
                    return
            image_x, image_y = self.to_image(event.x, event.y)
            candidates = []
            for ann in self.record.annotations:
                if len(ann.bbox) != 4:
                    continue
                x, y, w, h = ann.bbox
                if x <= image_x <= x + w and y <= image_y <= y + h:
                    candidates.append((w * h, ann.id))
            selected = min(candidates)[1] if candidates else None
            if selected is None or self.space_pressed:
                self._pan_press(event)
            elif self.geometry_mode == "rect":
                ann = next((item for item in self.record.annotations if item.id == selected), None)
                if ann:
                    self.checkpoint()
                    self.edit_state = {
                        "id": ann.id, "handle": "move", "start": (image_x, image_y),
                        "bbox": list(ann.bbox), "points": [list(p) for p in ann.points],
                        "obb": [list(p) for p in ann.obb], "orientation": [list(p) for p in ann.orientation],
                        "moved": False,
                    }
                    self.configure(cursor="fleur")
            self.selected_id = selected
            self.on_select(selected)
            self.redraw()
        elif self.mode == "box":
            self.drag_start = self.to_image(event.x, event.y)
        elif self.mode == "polygon":
            self.polygon_points.append(list(self.to_image(event.x, event.y)))
            self.redraw()
        elif self.mode in {"sam_click", "sam_positive", "sam_negative"}:
            x, y = self.to_image(event.x, event.y)
            label = 0 if self.mode == "sam_negative" else 1
            if self.mode == "sam_click":
                # Each SAM ON click starts a new point-only candidate.  The
                # regular SAM +/- modes keep accumulating refinement points.
                self.prompt_points = [(x, y, label)]
            else:
                self.prompt_points.append((x, y, label))
            self.redraw()
            if self.on_prompt:
                self.on_prompt(x, y, label)
        elif self.mode == "orientation":
            ann = next((item for item in self.record.annotations if item.id == self.selected_id), None)
            if ann and len(ann.bbox) == 4:
                x, y, w, h = ann.bbox
                center = [x + w / 2, y + h / 2]
                tip = list(self.to_image(event.x, event.y))
                self.checkpoint()
                ann.orientation = [center, tip]
                ann.source = "manual"
                ann.confidence = None
                ann.approved = False
                self.record.review_status = "draft"
                self.on_change()
                self.on_select(ann.id)
                self.redraw()

    def _drag(self, event) -> None:
        if self.edit_state:
            self._drag_rect_edit(event)
            return
        if self.pan_start:
            self._pan_drag(event)
            return
        if self.mode != "box" or not self.drag_start:
            return
        if self.preview_item:
            self.delete(self.preview_item)
        x1, y1 = self.to_canvas(*self.drag_start)
        x2, y2 = event.x, event.y
        self.preview_item = self.create_rectangle(x1, y1, x2, y2, outline="#ffffff", dash=(5, 3), width=2)

    def _release(self, event) -> None:
        if self.edit_state:
            state = self.edit_state
            self.edit_state = None
            if state.get("moved") and self.record:
                ann = next((item for item in self.record.annotations if item.id == state["id"]), None)
                if ann:
                    ann.source = "manual"
                    ann.confidence = None
                    ann.approved = False
                    self.record.review_status = "draft"
                    self.on_change()
                    self.on_select(ann.id)
            self.configure(cursor="arrow")
            self.redraw()
            return
        if self.pan_start:
            self._pan_release(event)
            return
        if self.mode != "box" or not self.drag_start or not self.record:
            return
        x1, y1 = self.drag_start
        x2, y2 = self.to_image(event.x, event.y)
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        self.drag_start = None
        self.preview_item = None
        if w >= 3 and h >= 3:
            self.checkpoint()
            ann = Annotation.create_box(self.active_class_id, [x, y, w, h])
            ann.attributes.update(self.default_attributes)
            self.record.annotations.append(ann)
            self.record.review_status = "draft"
            self.selected_id = ann.id
            self.on_select(ann.id)
            self.on_change()
        self.redraw()
        self._notify_view()

    def _drag_rect_edit(self, event) -> None:
        if not self.edit_state or not self.record or not self.image:
            return
        ann = next((item for item in self.record.annotations if item.id == self.edit_state["id"]), None)
        if not ann:
            return
        start_x, start_y = self.edit_state["start"]
        current_x, current_y = self.to_image(event.x, event.y)
        x, y, w, h = self.edit_state["bbox"]
        x1, y1, x2, y2 = x, y, x + w, y + h
        handle = self.edit_state["handle"]
        if handle == "move":
            dx, dy = current_x - start_x, current_y - start_y
            dx = min(max(dx, -x1), self.image.width - x2)
            dy = min(max(dy, -y1), self.image.height - y2)
            x1, x2, y1, y2 = x1 + dx, x2 + dx, y1 + dy, y2 + dy
        else:
            if "w" in handle:
                x1 = min(current_x, x2 - 3)
            if "e" in handle:
                x2 = max(current_x, x1 + 3)
            if "n" in handle:
                y1 = min(current_y, y2 - 3)
            if "s" in handle:
                y2 = max(current_y, y1 + 3)
            x1, x2 = min(max(x1, 0), self.image.width), min(max(x2, 0), self.image.width)
            y1, y2 = min(max(y1, 0), self.image.height), min(max(y2, 0), self.image.height)
        ann.bbox = [x1, y1, max(3, x2 - x1), max(3, y2 - y1)]
        old_x, old_y, old_w, old_h = self.edit_state["bbox"]
        new_x, new_y, new_w, new_h = ann.bbox
        def transform(points):
            return [
                [new_x + (px - old_x) * new_w / max(old_w, 1e-6), new_y + (py - old_y) * new_h / max(old_h, 1e-6)]
                for px, py in points
            ]
        ann.points = transform(self.edit_state["points"])
        ann.obb = transform(self.edit_state["obb"])
        ann.orientation = transform(self.edit_state["orientation"])
        self.edit_state["moved"] = True
        self.redraw()

    def _space_down(self, _event=None) -> None:
        self.space_pressed = True
        self.configure(cursor="fleur")

    def _space_up(self, _event=None) -> None:
        self.space_pressed = False
        if not self.pan_start:
            self.configure(cursor="arrow" if self.mode == "select" else "crosshair")

    def _pan_press(self, event) -> None:
        if not self.image:
            return
        self.pan_start = (event.x, event.y)
        self.pan_origin = (self.offset_x, self.offset_y)
        self.configure(cursor="fleur")

    def _pan_drag(self, event) -> None:
        if not self.pan_start or not self.pan_origin:
            return
        dx, dy = event.x - self.pan_start[0], event.y - self.pan_start[1]
        self.offset_x = self.pan_origin[0] + dx
        self.offset_y = self.pan_origin[1] + dy
        self.redraw()

    def _pan_release(self, _event=None) -> None:
        self.pan_start = None
        self.pan_origin = None
        self.configure(cursor="arrow" if self.mode == "select" else "crosshair")

    def _double_click(self, _event) -> None:
        if self.mode != "polygon" or not self.record or len(self.polygon_points) < 3:
            return
        xs = [point[0] for point in self.polygon_points]
        ys = [point[1] for point in self.polygon_points]
        self.checkpoint()
        ann = Annotation.create_box(self.active_class_id, [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)])
        ann.attributes.update(self.default_attributes)
        ann.kind = "polygon"
        ann.points = [list(point) for point in self.polygon_points]
        self.record.annotations.append(ann)
        self.record.review_status = "draft"
        self.polygon_points.clear()
        self.selected_id = ann.id
        self.on_select(ann.id)
        self.on_change()
        self.redraw()

    def _wheel(self, event) -> None:
        if not self.image:
            return
        old_scale = self.scale
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.scale = min(max(self.scale * factor, 0.05), 8.0)
        image_x, image_y = (event.x - self.offset_x) / old_scale, (event.y - self.offset_y) / old_scale
        self.offset_x = event.x - image_x * self.scale
        self.offset_y = event.y - image_y * self.scale
        self.redraw()
        self._notify_view()

    def delete_selected(self) -> None:
        if not self.record or not self.selected_id:
            return
        self.checkpoint()
        self.record.annotations = [ann for ann in self.record.annotations if ann.id != self.selected_id]
        self.selected_id = None
        self.on_select(None)
        self.on_change()
        self.redraw()

    def cancel_action(self) -> None:
        self.drag_start = None
        self.edit_state = None
        self.polygon_points.clear()
        if self.preview_item:
            self.delete(self.preview_item)
        self.preview_item = None
        self.redraw()

    def clear_prompts(self) -> None:
        self.prompt_points.clear()
        self.redraw()
