"""Exercise reviewed Studio methods with no Qt, NPU, network or robot."""
import ast
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.studio_integration.blockly.PythonScriptExecutor import PythonScriptExecutor
from tools.studio_integration.blockly.prepare_patch import patch_pick, patch_loops, patch_editor


BASELINE = Path(__file__).parent / 'fixtures/studio_blockly_pick.py'


def make_pick():
    namespace = {'math': math, 'time': time, 'QPointF': lambda x, y: (x, y),
                 'log_system': Mock(), 'log_error': Mock(),
                 'LogModule': SimpleNamespace(SCRIPT='script'),
                 'LogAction': SimpleNamespace(STOPPED='stopped', RUNNING='running', COMPLETED='completed'),
                 'LogLevel': SimpleNamespace(ERROR='error')}
    exec(compile(patch_pick(BASELINE.read_text(encoding='utf8')), 'reviewed-Pick', 'exec'), namespace)
    obj = namespace['PickFixture']()
    obj.exit_loop = False
    obj.end_effectors = {}
    obj.tracking_parameters = {}
    obj.robot_index = 0
    obj.current_script_id = None
    obj.script_status = SimpleNamespace(emit=Mock())
    obj.event_loop = SimpleNamespace(processEvents=lambda: None)
    obj.is_sleeping_done = SimpleNamespace(emit=Mock())
    obj.set_tracking_parameters = Mock()
    obj.robot_interface = FakeRobot()
    obj.script_executor = PythonScriptExecutor(obj)
    obj.set_robot_end_effector(0, 'vacuum', 0, 200, 200, 0, 0)
    return obj


class FakeRobot:
    def __init__(self, pick=None, stop_at=None):
        self.z = None
        self.events = []
        self.pick = pick
        self.stop_at = stop_at
        self.after = None

    def record(self, event):
        self.events.append(event)
        if len(self.events) == self.stop_at:
            self.pick.exit_loop = True
            self.pick.script_executor.cancelled = True
        if self.after:
            self.after(event)

    def move(self, **kw):
        if kw.get('Z') is not None:
            self.z = kw['Z']
        self.record(('move', kw))

    def set_output(self, pin, state):
        self.record(('output', pin, state, self.z))

    def set_all_outputs(self, state):
        self.record(('cleanup', state))

    def sleep(self, **kw):
        self.record(('sleep', kw))


class PlacementTests(unittest.TestCase):
    def prepare(self, kind='vacuum'):
        pick = make_pick()
        pick.robot_interface = FakeRobot()
        pick.end_effectors[0]['type'] = kind
        return pick

    def test_vacuum_release_at_destination_for_each_layer(self):
        for z in [-650, -620]:
            pick = self.prepare()
            pick.move_place_xyangle(0, -320, -80, 32, -600, z)
            events = pick.robot_interface.events
            self.assertEqual([v[0] for v in events], ['move', 'move', 'output', 'sleep', 'move'])
            self.assertEqual(events[2], ('output', 0, 0, z))
            self.assertEqual(events[0][1]['W'], 32)
            self.assertEqual(events[0][1]['X'], -320)
            self.assertEqual(events[-1][1]['Z'], -600)

    def test_pick_vacuum_still_starts_before_descent(self):
        pick = self.prepare()
        pick.move_pick_xyangle(0, 10, 20, -170, -600, -840, tracker_id=0)
        events = pick.robot_interface.events
        self.assertEqual(events[1], ('output', 0, 1, -600))
        self.assertTrue(events[2][1]['sync'])
        self.assertEqual(events[0][1]['W'], -170)

    def test_gripper_closes_and_opens_at_target(self):
        for state in [0, 1]:
            pick = self.prepare('gripper')
            pick.move_pick_xyangle(0, 10, 20, 90, -600, -700, _io_status=state)
            self.assertEqual(pick.robot_interface.events[2], ('output', 0, state, -700))

    def test_tray_vacuum_release_also_at_destination(self):
        pick = self.prepare()
        pick.tray_config = {'conveyor_to_robot_direction': 0}
        pick.robot_interface.set_sync_angle = Mock()
        pick.robot_interface.set_sync_vel = Mock()
        pick.cal_time_offset = lambda _: 0
        pick.move_place_tray(0, [10, 20, -650, 0, time.time()], 45, -600)
        outputs = [e for e in pick.robot_interface.events if e[0] == 'output']
        self.assertEqual(outputs, [('output', 0, 0, -650)])

    def test_cancel_between_every_pick_and_place_command(self):
        for state in [0, 1]:
            for stop_at in range(1, 6):
                pick = self.prepare()
                robot = FakeRobot(pick, stop_at)
                pick.robot_interface = robot
                pick.script_executor.robot_interface = robot
                success, error = pick.script_executor.execute_script(
                    f'pick.move_pick_xyangle(0, 10, 20, 30, -600, -700, _io_status={state})\nrobot.move(X=999)')
                self.assertTrue(success, error)
                self.assertTrue(pick.script_executor.was_cancelled)
                self.assertEqual(len(robot.events), stop_at)


class CancellationTests(unittest.TestCase):
    def test_old_wait_loop_cancels_without_none_arithmetic(self):
        pick = make_pick()
        pick.robot_interface = FakeRobot()
        pick.script_executor.robot_interface = pick.robot_interface
        def stop():
            pick.exit_loop = True
        pick.event_loop.processEvents = stop
        code = 'obj=None\nwhile not obj and not pick.exit_loop:\n pick.event_loop.processEvents()\n obj=[1,2,3]\nangle=None\nangle/180\nrobot.move(X=999)'
        result = pick.script_executor.execute_script(code)
        self.assertEqual(result, (True, None))
        self.assertTrue(pick.script_executor.was_cancelled)
        self.assertEqual(pick.robot_interface.events, [])

    def test_direct_robot_commands_stop_before_next_script_line(self):
        pick = make_pick()
        robot = FakeRobot(pick, 1)
        pick.script_executor.robot_interface = robot
        self.assertEqual(pick.script_executor.execute_script('robot.move(X=1)\nrobot.move(X=2)'), (True, None))
        self.assertEqual(len(robot.events), 1)

    def test_status_is_stopped_not_completed_or_error(self):
        pick = make_pick()
        pick.exit_loop = True
        robot = FakeRobot(pick, 1)
        pick.robot_interface = robot
        pick.script_executor.robot_interface = robot
        pick.execute_script_with_status('test', 'robot.move(X=1)\nrobot.move(X=2)')
        statuses = [c.args[1] for c in pick.script_status.emit.call_args_list]
        self.assertEqual(statuses, ['run_running', 'stop_stopped'])

    def test_stop_keeps_executor_busy_until_stack_unwinds(self):
        pick = make_pick()
        pick.robot_interface = FakeRobot()
        pick.script_executor.is_running = True
        pick.stop_script('test')
        self.assertTrue(pick.script_executor.is_running)
        self.assertTrue(pick.script_executor.cancelled)
        self.assertEqual(pick.script_executor.execute_script('pass'), (False, 'Has running script'))

    def test_restart_resets_cancelled_state_and_restores_trace(self):
        pick = make_pick()
        robot = FakeRobot(pick, 1)
        pick.script_executor.robot_interface = robot
        previous = sys.gettrace()
        pick.script_executor.execute_script('robot.move(X=1)')
        self.assertIs(sys.gettrace(), previous)
        self.assertTrue(pick.script_executor.was_cancelled)
        pick.exit_loop = False
        robot.stop_at = None
        self.assertEqual(pick.script_executor.execute_script('robot.move(X=2)'), (True, None))
        self.assertFalse(pick.script_executor.was_cancelled)
        self.assertIs(sys.gettrace(), previous)

    def test_syntax_failure_and_vision_only_executor(self):
        executor = PythonScriptExecutor(vision_instance=SimpleNamespace(count=0))
        self.assertEqual(executor.execute_script('vision.count += 1'), (True, None))
        self.assertEqual(executor.vision_instance.count, 1)
        self.assertFalse(executor.execute_script('if:')[0])
        self.assertFalse(executor.is_running)

    def test_legacy_stdout_redirect_is_restored_after_success_and_error(self):
        executor = PythonScriptExecutor()
        previous = sys.stdout
        self.assertEqual(executor.execute_script('import sys, io\nsys.stdout=io.StringIO()'), (True, None))
        self.assertIs(sys.stdout, previous)
        self.assertFalse(executor.execute_script('import sys, io\nsys.stdout=io.StringIO()\nraise ValueError("test")')[0])
        self.assertIs(sys.stdout, previous)

    def test_completion_message_reaches_studio_status(self):
        pick = make_pick()
        pick.exit_loop = True
        robot = FakeRobot()
        pick.robot_interface = robot
        pick.script_executor.robot_interface = robot
        pick.execute_script_with_status('test', "pick.set_script_completion_message('Thùng đầy')")
        self.assertIn(('test', 'run_completed', 'Thùng đầy', 0),
                      [c.args for c in pick.script_status.emit.call_args_list])


class ObjectWaitTests(unittest.TestCase):
    def test_pair_spacing_heading_height_and_mirrored_tool_order(self):
        pick = make_pick()
        self.assertTrue(pick.packing_pair_fits([-250, -80, -650], [-110, -80, -650], 0, 70, 0))
        self.assertTrue(pick.packing_pair_fits([-250, -80, -650], [-110, -80, -650], 180, 70, 0))
        self.assertTrue(pick.packing_pair_fits([0, 0, -650], [0, 140, -650], 90, 70, 0))
        self.assertFalse(pick.packing_pair_fits([-250, -80, -650], [-120, -80, -650], 0, 70, 0))
        self.assertFalse(pick.packing_pair_fits([0, 0, -650], [140, 0, -620], 0, 70, 0))
        self.assertFalse(pick.packing_pair_fits([0, 0, -650], [140, 0, -650], 90, 70, 0))
        self.assertFalse(pick.packing_pair_fits([0, 0, -650], [0, 0, -650], 0, 0, 0))
        with self.assertRaises(ValueError):
            pick.packing_pair_fits([0, 0], [0, 0, -650], 0, 70, 0)
        with self.assertRaises(ValueError):
            pick.packing_pair_fits([0, 0, -650], [140, 0, -650], float('nan'), 70, 0)

    def test_timeout_does_not_consume_object_after_deadline(self):
        pick = make_pick()
        now = [0.0]
        pick.sleep = lambda time_ms: now.__setitem__(0, now[0] + time_ms / 1000)
        pick.get_object_in_robot_area = Mock(return_value=None)
        with patch('time.monotonic', side_effect=lambda: now[0]):
            self.assertIsNone(pick.wait_object_in_robot_area(0, 200))
        self.assertAlmostEqual(now[0], .2)
        self.assertEqual(pick.get_object_in_robot_area.call_count, 4)

    def test_valid_heading_preserved_and_invalid_positions_rejected(self):
        pick = make_pick()
        obj = [10, 20, -179.9, 0]
        pick.get_object_in_robot_area = Mock(return_value=obj)
        self.assertIs(pick.wait_object_in_robot_area(0, 2000), obj)
        pick.get_object_in_robot_area.assert_called_with(object_type=0)
        for obj in [[1], [1, 2, float('nan')], [1, 2, float('inf')]]:
            pick.get_object_in_robot_area.return_value = obj
            with self.assertRaises(ValueError):
                pick.wait_object_in_robot_area(0, 2000)

    def test_invalid_timeouts_and_grid_sizes(self):
        pick = make_pick()
        for timeout in [-1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                pick.wait_object_in_robot_area(0, timeout)
        self.assertEqual(pick.packing_capacity(2, 2, 2), 8)
        for values in [(0, 2, 2), (2, -1, 2), (2, 2.5, 2), (True, 2, 2), (float('inf'), 2, 2)]:
            with self.assertRaises(ValueError):
                pick.packing_capacity(*values)

    def test_event_cancellation_does_not_dequeue(self):
        pick = make_pick()
        pick.get_object_in_robot_area = Mock(return_value=[1, 2, 3])
        pick.event_loop.processEvents = lambda: setattr(pick, 'exit_loop', True)
        self.assertEqual(pick.script_executor.execute_script('pick.wait_object_in_robot_area(0, 2000)'), (True, None))
        self.assertTrue(pick.script_executor.was_cancelled)
        pick.get_object_in_robot_area.assert_not_called()


class PatchTests(unittest.TestCase):
    def test_loop_generators_and_toolbox_are_targeted(self):
        original = "branch = '  pick.event_loop.processEvents()\\n' + branch;\n" * 4
        self.assertEqual(patch_loops(original).count('pick.check_script_cancelled()'), 4)
        with self.assertRaises(ValueError):
            patch_loops('different version')
        original = "import './blocks/other-blocks';\n{ kind: \"block\", type: \"get_object_in_robot_area\" },"
        self.assertIn("import './blocks/packing-blocks';", patch_editor(original))
        self.assertIn('script_completion_message', patch_editor(original))


if __name__ == '__main__':
    unittest.main()
