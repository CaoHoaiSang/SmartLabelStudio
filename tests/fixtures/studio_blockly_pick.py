"""Reviewed Radxa method fixture; no initialization or hardware imports."""
class PickFixture:
    def execute_script(self, code):
        """Execute a Python script"""
        if self.script_executor is None:
            print("Script executor not initialized")
            return False, "Script executor not initialized"

        return self.script_executor.execute_script(code)

    def execute_script_with_status(self, script_id, code, robot_index = None):
        if robot_index is not None and robot_index != self.robot_index:
            return

        if self.exit_loop == False:
            self.script_status.emit(script_id or "", 'run_error', "Pick is running", self.robot_index)
            log_error(LogModule.SCRIPT, LogLevel.ERROR, f"Script {script_id} execution failed: Pick is running")
            return False

        self.current_script_id = script_id
        self.script_status.emit(script_id or "", 'run_running', "Script is running", self.robot_index)
        log_system(LogModule.SCRIPT, LogAction.RUNNING, f"Script {script_id} execution started")

        self.exit_loop = False
        # Thực thi script
        success, error = self.execute_script(code)
        self.exit_loop = True
        # Gửi trạng thái kết thúc - CHẠY XONG hoặc CHẠY LỖI
        if success:
            self.script_status.emit(script_id or "", 'run_completed', "Script execution completed successfully", self.robot_index)
            log_system(LogModule.SCRIPT, LogAction.COMPLETED, f"Script {script_id} execution completed successfully")
            self.robot_interface.set_all_outputs(0)
        else:
            self.script_status.emit(script_id or "", 'run_error', error, self.robot_index)
            log_error(LogModule.SCRIPT, LogLevel.ERROR, f"Script {script_id} execution failed: {error}")
            self.robot_interface.set_all_outputs(0)

        # Xóa script_id hiện tại
        self.current_script_id = None

        return success

    def stop_script(self, script_id, robot_index = None):
        # Stop an active pick loop for the *matching* script only.
        # This avoids stopping other concurrent programs that happen to share the same robot.
        if robot_index is not None and robot_index != self.robot_index:
            return

        # Best-effort: UI có thể gửi `script_id` sai khi hiển thị nhiều program song song.
        # Nếu robot này đang chạy (exit_loop == False) thì vẫn dừng theo script đang chạy thật.
        if self.exit_loop == True:
            return

        effective_script_id = script_id
        if self.current_script_id is not None and script_id is not None and self.current_script_id != script_id:
            effective_script_id = self.current_script_id
        elif self.current_script_id is not None:
            effective_script_id = self.current_script_id

        # if self.script_executor is None or not self.script_executor.is_running:
        #     self.script_status.emit(script_id, 'stop_error', "No script is running")
        #     return

        self.exit_loop = True

        self.robot_interface.set_all_outputs(0)

        # Gửi trạng thái dừng
        self.script_status.emit(effective_script_id, 'stop_stopped', "Script execution stopped by user", f'pick_{self.robot_index}')
        log_system(LogModule.SCRIPT, LogAction.STOPPED, f"Script {effective_script_id} execution stopped by user")

        # Đặt cờ is_running thành False để script dừng ở lần lặp tiếp theo
        self.script_executor.is_running = False

    def python_script_has_error(self, script_id, robot_index = None):
        if robot_index is not None and robot_index >= 0 and robot_index != self.robot_index:
            return

        if self.exit_loop == False:
            self.exit_loop = True

        # Đặt cờ is_running thành False để script dừng ở lần lặp tiếp theo
        self.script_executor.is_running = False

    def set_robot_end_effector(self, id, type, pinout, delay_in, delay_out, offset_x, offset_y):
        self.end_effectors[id] = {
            'type': type,
            'pinout': pinout,
            'delay_in': delay_in,
            'delay_out': delay_out,
            'offset_x': offset_x,
            'offset_y': offset_y
        }

    def set_end_effector(self, id, state):
        if id is not None:
            if id in self.end_effectors:
                self.robot_interface.set_output(self.end_effectors[id]['pinout'], state)
        else:
            # If id is None, set state for all configured end effectors
            for effector_id in self.end_effectors:
                self.robot_interface.set_output(self.end_effectors[effector_id]['pinout'], state)

    def get_end_effector_delay_in(self, id):
        if id is not None and id in self.end_effectors:
            return self.end_effectors[id]['delay_in']
        else:
            return 0

    def get_end_effector_delay_out(self, id):
        if id is not None and id in self.end_effectors:
            return self.end_effectors[id]['delay_out']
        else:
            return 0

    def get_end_effector_offset(self, id):
        if id is not None and id in self.end_effectors:
            return self.end_effectors[id]['offset_x'], self.end_effectors[id]['offset_y']
        else:
            return 0, 0

    def get_tracking_parameters_delay_time(self, tracker_id):
        if tracker_id in self.tracking_parameters:
            return self.tracking_parameters[tracker_id]['delay_time']
        else:
            return 0

    def sleep(self, time_ms=100, tracker_id=None):
        if tracker_id is None:
            self.robot_interface.sleep(time_ms = time_ms, sync = False)
            self.is_sleeping_done.emit(self.robot_index)
        else:
            self.set_tracking_parameters(tracker_id)
            self.robot_interface.sleep(time_ms = time_ms, sync = True)

    def move(self, X=None, Y=None, Z=None, W=None, U=None, V=None, tracker_id=None, F=None, A=None, S=None, E=None, J=None):
        if tracker_id is not None:
            self.set_tracking_parameters(tracker_id)
            self.robot_interface.move(X, Y, Z, W, U, V, F, A, S, E, J, sync = True, delay_time = self.get_tracking_parameters_delay_time(tracker_id))
        else:
            self.robot_interface.move(X, Y, Z, W, U, V, F, A, S, E, J, sync = False)

    def move_pick_xyangle(self, end_effector_id=None, x=None, y=None, angle=None, z_move=None, z_pick=None, tracker_id=None, F=None, A=None, S=None, E=None, J=None, _io_status = 1):
        _is_sync = False
        if tracker_id is not None:
            self.set_tracking_parameters(tracker_id)
            _is_sync = True

        _end_effecter_type = "gripper"
        _offset_x = 0
        _offset_y = 0
        if end_effector_id is not None:
            _end_effecter_type = self.end_effectors[end_effector_id]['type']

            _offset_x, _offset_y = self.get_end_effector_offset(end_effector_id)

        # Move to pick position with all parameters
        self.robot_interface.move(X=x - _offset_x, Y=y - _offset_y, Z=z_move, W=angle, F=F, A=A, S=S, E=E, J=J, sync=_is_sync, time_offset=self.get_tracking_parameters_delay_time(tracker_id))

        _end_effector_delay_time = 0
        if _io_status == 1:
            _end_effector_delay_time = self.get_end_effector_delay_in(end_effector_id)
        else:
            _end_effector_delay_time = self.get_end_effector_delay_out(end_effector_id)

        # Different behavior based on end effector type
        if _end_effecter_type == "vacuum":
            self.set_end_effector(end_effector_id, _io_status)
            self.robot_interface.move(Z=z_pick, F=F, sync=_is_sync)
            self.robot_interface.sleep(time_ms=_end_effector_delay_time, sync=_is_sync)
            self.robot_interface.move(Z=z_move, F=F, sync=_is_sync)
        else:
            self.robot_interface.move(Z=z_pick, F=F, sync=_is_sync)
            self.set_end_effector(end_effector_id, _io_status)
            self.robot_interface.sleep(time_ms=_end_effector_delay_time, sync=_is_sync)
            self.robot_interface.move(Z=z_move, F=F, sync=_is_sync)

    def move_place_xyangle(self, end_effector_id=None, x=None, y=None, angle=None, z_move=None, z_place=None, tracker_id=None, F=None, A=None, S=None, E=None, J=None):
        self.move_pick_xyangle(end_effector_id, x, y, angle, z_move, z_place, tracker_id, F, A, S, E, J, 0)

    def get_nearest_object(self, object_type=None, end_effector_id=None):
        if end_effector_id is not None:
            _offset_x, _offset_y = self.get_end_effector_offset(end_effector_id)

            current_endeffector_x = self.robot_interface.X + _offset_x
            current_endeffector_y = self.robot_interface.Y + _offset_y

        else:
            current_endeffector_x = self.robot_interface.X
            current_endeffector_y = self.robot_interface.Y

        _end_x, _end_y = self.convert_robot_pos_to_conveyor_pos(current_endeffector_x, current_endeffector_y)

        if self.is_has_tracking_object == True:
            obj_para = self.tracking_manager.getObjectForPick(None, None, self.robot_index, object_type, [_end_x, _end_y])

            if len(obj_para) <= 4:
                self.try_get_tracking_object_count += 1
                if self.try_get_tracking_object_count >= 2:
                    self.is_has_tracking_object = False
                return None
            else:
                self.try_get_tracking_object_count = 0

        else:
            return None

        # Extract object parameters
        objs_cur_x = obj_para[0]
        objs_cur_y = obj_para[1]
        objs_angle = obj_para[2]

        # Map from conveyor coordinates to robot coordinates
        _new_pos = self.mapping_matrix.map(QPointF(objs_cur_x, objs_cur_y))
        obj_pos_x = _new_pos.x()
        obj_pos_y = _new_pos.y()

        self.current_tracking_speed = obj_para[4]
        self.current_execution_time = obj_para[3]

        angle = self._normalize_angle(objs_angle + 90)

        return [obj_pos_x, obj_pos_y, angle, obj_para[5]]

    def get_object_in_robot_area(self, object_type=None, min_pick_y = None, max_pick_y = None):
        if min_pick_y is None:
            min_pick_y = self.min_pick_y
        if max_pick_y is None:
            max_pick_y = self.max_pick_y

        if self.is_has_tracking_object == True:
            obj_para = self.tracking_manager.getObjectForPick(min_pick_y, max_pick_y, self.robot_index, object_type, None)

            if len(obj_para) <= 4:
                self.try_get_tracking_object_count += 1
                if self.try_get_tracking_object_count >= 2:
                    self.is_has_tracking_object = False
                return None
            else:
                self.try_get_tracking_object_count = 0

        else:
            return None

        # Extract object parameters
        objs_cur_x = obj_para[0]
        objs_cur_y = obj_para[1]
        objs_angle = obj_para[2]

        # Map from conveyor coordinates to robot coordinates
        _new_pos = self.mapping_matrix.map(QPointF(objs_cur_x, objs_cur_y))
        obj_pos_x = _new_pos.x()
        obj_pos_y = _new_pos.y()

        self.current_tracking_speed = obj_para[4]
        self.current_execution_time = obj_para[3]

        angle = self._normalize_angle(objs_angle + 90)

        return [obj_pos_x, obj_pos_y, angle, obj_para[5]]

    def move_place_tray(self, end_effector_id=None, tray_pos=None, angle=None, z_move=None, F=None, A=None, S=None, E=None, J=None):
        if tray_pos is None or len(tray_pos) < 4:
            return

        self.robot_interface.set_sync_angle(self.tray_config['conveyor_to_robot_direction'])
        self.robot_interface.set_sync_vel(tray_pos[3])

        _new_delay_time = time.time() - tray_pos[4] + self.cal_time_offset(tray_pos[3])
        sync_value = True

        _end_effecter_type = "gripper"
        _offset_x = 0
        _offset_y = 0
        if end_effector_id is not None:
            _end_effecter_type = self.end_effectors[end_effector_id]['type']

            _offset_x, _offset_y = self.get_end_effector_offset(end_effector_id)

        else:
            _end_effecter_type = "vacuum"

        # Move to place position with all parameters
        self.robot_interface.move(X=tray_pos[0] - _offset_x, Y=tray_pos[1] - _offset_y, Z=z_move, W=angle, F=F, A=A, S=S, E=E, J=J, sync=sync_value, time_offset=_new_delay_time)

        # Different behavior based on end effector type
        if _end_effecter_type == "vacuum":
            self.set_end_effector(end_effector_id, 0)
            self.robot_interface.move(Z=tray_pos[2], F=F, sync=sync_value)
            self.robot_interface.sleep(time_ms=self.get_end_effector_delay_out(end_effector_id), sync=sync_value)
            self.robot_interface.move(Z=z_move, F=F, sync=sync_value)
        else:
            self.robot_interface.move(Z=tray_pos[2], F=F, sync=sync_value)
            self.set_end_effector(end_effector_id, 0)
            self.robot_interface.sleep(time_ms=self.get_end_effector_delay_out(end_effector_id), sync=sync_value)
            self.robot_interface.move(Z=z_move, F=F, sync=sync_value)
