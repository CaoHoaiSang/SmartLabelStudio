"""Studio script execution with cooperative cancellation between commands."""
import sys
import traceback


class ScriptCancelled(BaseException):
    """Normal operator cancellation, rather than a program failure."""


class PythonScriptExecutor:
    def __init__(self, pick_instance=None, vision_instance=None):
        self.pick_instance = pick_instance
        self.robot_interface = None if pick_instance is None else pick_instance.robot_interface
        self.vision_instance = vision_instance
        self.is_running = False
        self.cancelled = False
        self.was_cancelled = False

    def check_cancelled(self):
        if self.is_running and (self.cancelled or
                (self.pick_instance is not None and self.pick_instance.exit_loop)):
            raise ScriptCancelled()

    def execute_script(self, code):
        if self.is_running:
            return False, "Has running script"
        self.cancelled = False
        self.was_cancelled = False
        self.is_running = True
        filename = "<studio-script:{}>".format(id(self))
        previous_trace = sys.gettrace()
        previous_stdout = sys.stdout

        def trace(frame, event, arg):
            if frame.f_code.co_filename != filename:
                return None
            if event in ("line", "call"):
                self.check_cancelled()
            return trace

        try:
            compiled = compile(code, filename, "exec")
            self.check_cancelled()
            sys.settrace(trace)
            exec(compiled, {"robot": self.robot_interface, "pick": self.pick_instance,
                            "vision": self.vision_instance})
            self.check_cancelled()
            return True, None
        except ScriptCancelled:
            self.was_cancelled = True
            return True, None
        except Exception:
            return False, traceback.format_exc()
        finally:
            sys.settrace(previous_trace)
            sys.stdout = previous_stdout
            self.is_running = False
