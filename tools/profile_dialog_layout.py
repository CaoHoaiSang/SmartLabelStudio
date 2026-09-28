"""Reproducible popup timing/layout probe, using temporary projects only."""
import cProfile
import io
from pathlib import Path
import pstats
import sys
from tempfile import TemporaryDirectory
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import customtkinter as ctk
from smartlabel.project_store import ProjectStore
from smartlabel.hydroponic import apply_hydroponic_slot_template
from smartlabel.ui_components import ProjectSettingsDialog, HydroBundleConfigDialog


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main():
    with TemporaryDirectory() as temp:
        root = ctk.CTk()
        root.geometry("1200x800+40+40")
        store = ProjectStore(Path(temp))
        project = store.create_project("Timing fixture", task="classify")
        apply_hydroponic_slot_template(project)
        root.update()
        profiler = cProfile.Profile()
        for factory in (lambda: ProjectSettingsDialog(root, project, lambda: None),
                        lambda: HydroBundleConfigDialog(root, {})):
            start = time.perf_counter()
            profiler.enable()
            dialog = factory()
            constructed = time.perf_counter() - start
            deadline = time.monotonic() + .4
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            profiler.disable()
            print(type(dialog).__name__, "construct_ms", round(constructed * 1000), flush=True)
            if isinstance(dialog, ProjectSettingsDialog):
                print("attribute_toolbar", dialog.attribute_help.winfo_width(),
                      dialog.attribute_help.winfo_height(), flush=True)
                print("attribute_card_heights", [group["frame"].winfo_height()
                      for group in dialog.attribute_groups.values()], flush=True)
            for child in descendants(dialog):
                if isinstance(child, ctk.CTkLabel) and any(str(child.cget("text")).startswith(s)
                        for s in ("Mỗi tình trạng", "Thông tin đã có")):
                    print("description", child.winfo_width(), child.winfo_height(),
                          "parent", child.master.winfo_width(), "wrap", child.cget("wraplength"), flush=True)
            dialog.destroy()
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative").print_stats(24)
        print(output.getvalue())
        for timer in root.tk.call("after", "info"):
            root.after_cancel(timer)
        root.destroy()


if __name__ == "__main__":
    main()
