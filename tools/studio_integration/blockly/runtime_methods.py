"""Methods installed into the existing Radxa Pick class by prepare_patch.

This file has no Qt, camera or robot initialization; it is also the testable
source for the patch, rather than a second implementation of the controller.
"""
import math
import time


class ScriptPickMethods:
    def packing_pair_fits(self, first, second, angle, dx, dy):
        if len(first) != 3 or len(second) != 3:
            raise ValueError("Packing positions must contain X, Y and Z")
        values = [*first, *second, angle, dx, dy]
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Packing geometry must be finite")
        if math.hypot(dx, dy) < 0.01 or abs(first[2] - second[2]) > 0.01:
            return False
        radians = math.radians(angle)
        sep_x = 2 * (dx * math.cos(radians) - dy * math.sin(radians))
        sep_y = 2 * (dx * math.sin(radians) + dy * math.cos(radians))
        delta_x, delta_y = second[0] - first[0], second[1] - first[1]
        # Either tool can occupy the first cell; both packets have the same
        # requested final heading. Tolerance only covers numeric rounding.
        return min(math.hypot(delta_x-sep_x, delta_y-sep_y),
                   math.hypot(delta_x+sep_x, delta_y+sep_y)) <= 0.1

    def packing_capacity(self, cols, rows, layers):
        values = [cols, rows, layers]
        if any(isinstance(v, bool) or not math.isfinite(float(v)) or
               float(v) <= 0 or float(v) != int(v) for v in values):
            raise ValueError("Packing columns, rows and layers must be positive integers")
        return int(cols) * int(rows) * int(layers)

    def check_script_cancelled(self):
        executor = self.script_executor
        if executor is not None:
            executor.check_cancelled()

    def set_script_completion_message(self, message):
        self.check_script_cancelled()
        self.script_completion_message = str(message)

    def wait_object_in_robot_area(self, object_type=None, timeout_ms=0):
        timeout_ms = float(timeout_ms)
        if not math.isfinite(timeout_ms) or timeout_ms < 0:
            raise ValueError("Object wait timeout must be finite and non-negative")
        deadline = None if timeout_ms == 0 else time.monotonic() + timeout_ms / 1000.0
        while True:
            self.event_loop.processEvents()
            self.check_script_cancelled()
            if deadline is not None and time.monotonic() >= deadline:
                return None
            obj = self.get_object_in_robot_area(object_type=object_type)
            self.check_script_cancelled()
            if obj is not None:
                if len(obj) < 3 or not all(math.isfinite(float(v)) for v in obj[:3]):
                    raise ValueError("Invalid tracked object position or heading")
                return obj
            remaining_ms = 50 if deadline is None else min(50, (deadline - time.monotonic()) * 1000)
            if remaining_ms > 0:
                self.sleep(time_ms=remaining_ms)

    def move_pick_xyangle(self, end_effector_id=None, x=None, y=None, angle=None,
                          z_move=None, z_pick=None, tracker_id=None, F=None,
                          A=None, S=None, E=None, J=None, _io_status=1):
        self.check_script_cancelled()
        is_sync = tracker_id is not None
        if is_sync:
            self.set_tracking_parameters(tracker_id)
        effector_type = "gripper"
        offset_x = offset_y = 0
        if end_effector_id is not None:
            effector_type = self.end_effectors[end_effector_id]['type']
            offset_x, offset_y = self.get_end_effector_offset(end_effector_id)
        self.check_script_cancelled()
        self.robot_interface.move(X=x-offset_x, Y=y-offset_y, Z=z_move, W=angle,
                                  F=F, A=A, S=S, E=E, J=J, sync=is_sync,
                                  time_offset=self.get_tracking_parameters_delay_time(tracker_id))
        delay = (self.get_end_effector_delay_in(end_effector_id) if _io_status == 1
                 else self.get_end_effector_delay_out(end_effector_id))
        # Vacuum can start before descent when picking. Release must happen
        # only at the destination, for vacuum and gripper alike.
        early_vacuum = effector_type == "vacuum" and _io_status == 1
        if early_vacuum:
            self.check_script_cancelled()
            self.set_end_effector(end_effector_id, _io_status)
        self.check_script_cancelled()
        self.robot_interface.move(Z=z_pick, F=F, sync=is_sync)
        if not early_vacuum:
            self.check_script_cancelled()
            self.set_end_effector(end_effector_id, _io_status)
        self.check_script_cancelled()
        self.robot_interface.sleep(time_ms=delay, sync=is_sync)
        self.check_script_cancelled()
        self.robot_interface.move(Z=z_move, F=F, sync=is_sync)
        self.check_script_cancelled()
