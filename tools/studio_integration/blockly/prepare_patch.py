"""Build a reviewed, targeted Studio patch; do not contact hardware here."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replace_method(source, name, replacement):
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef))
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = source.splitlines(keepends=True)
    return ''.join(lines[:node.lineno-1]) + replacement.rstrip() + '\n' + ''.join(lines[node.end_lineno:])


def method_text(source, name):
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef))
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return '\n'.join(source.splitlines()[node.lineno-1:node.end_lineno])


def patch_pick(source):
    methods = (HERE / 'runtime_methods.py').read_text(encoding='utf8')
    source = replace_method(source, 'move_pick_xyangle', method_text(methods, 'move_pick_xyangle'))
    anchor = '    def set_robot_end_effector('
    if source.count(anchor) != 1:
        raise ValueError('Unsupported Pick source')
    additions = '\n\n'.join(method_text(methods, n) for n in
                            ['check_script_cancelled', 'set_script_completion_message',
                             'packing_capacity', 'packing_pair_fits', 'wait_object_in_robot_area'])
    source = source.replace(anchor, additions + '\n\n' + anchor)
    # The tray helper has its own placement sequence; it must release at Z too.
    tray = method_text(source, 'move_place_tray')
    old = "            self.set_end_effector(end_effector_id, 0)\n            self.robot_interface.move(Z=tray_pos[2], F=F, sync=sync_value)"
    if tray.count(old) != 1:
        raise ValueError('Unsupported tray placement sequence')
    tray = tray.replace(old, "            self.robot_interface.move(Z=tray_pos[2], F=F, sync=sync_value)\n            self.set_end_effector(end_effector_id, 0)")
    source = replace_method(source, 'move_place_tray', tray)
    # Cancel before calls that can command movement/IO or consume an object.
    for name in ['set_end_effector', 'sleep', 'move', 'move_place_tray',
                 'get_object_in_robot_area', 'get_nearest_object']:
        text = method_text(source, name)
        lines = text.splitlines()
        lines.insert(1, '        self.check_script_cancelled()')
        guarded = []
        for line in lines:
            if ('self.robot_interface.' in line and '(' in line or
                    'self.set_end_effector(' in line or 'self.set_tracking_parameters(' in line):
                guarded.append(line[:len(line)-len(line.lstrip())] + 'self.check_script_cancelled()')
            guarded.append(line)
        source = replace_method(source, name, '\n'.join(guarded))
    execution = method_text(source, 'execute_script_with_status')
    execution = execution.replace('        self.current_script_id = script_id',
                                  '        self.script_completion_message = None\n        self.current_script_id = script_id')
    execution = execution.replace('        if success:\n',
        "        if self.script_executor.was_cancelled:\n"
        "            self.script_status.emit(script_id or \"\", 'stop_stopped', 'Script cancelled', self.robot_index)\n"
        "            self.robot_interface.set_all_outputs(0)\n"
        "        elif success:\n")
    execution = execution.replace("'run_completed', \"Script execution completed successfully\", self.robot_index)",
                                  "'run_completed', self.script_completion_message or \"Script execution completed successfully\", self.robot_index)")
    source = replace_method(source, 'execute_script_with_status', execution)
    for name in ['stop_script', 'python_script_has_error']:
        text = method_text(source, name)
        text = text.replace('self.script_executor.is_running = False',
                            'self.script_executor.cancelled = True')
        source = replace_method(source, name, text)
    ast.parse(source)
    return source


def patch_editor(source):
    source = source.replace("import './blocks/other-blocks';",
                            "import './blocks/other-blocks';\nimport './blocks/packing-blocks';")
    anchor = '{ kind: "block", type: "get_object_in_robot_area" },'
    if source.count(anchor) != 1:
        raise ValueError('Unsupported Blockly toolbox')
    return source.replace(anchor, anchor + '\n              { kind: "block", type: "wait_object_in_robot_area" },\n'
                          '              { kind: "block", type: "packing_capacity" },\n'
                          '              { kind: "block", type: "packing_pair_fits" },\n'
                          '              { kind: "block", type: "script_completion_message" },')


def patch_loops(source):
    anchor = "branch = '  pick.event_loop.processEvents()\\n' + branch;"
    if source.count(anchor) != 4:
        raise ValueError('Unsupported loop generators')
    return source.replace(anchor, "branch = '  pick.event_loop.processEvents()\\n  pick.check_script_cancelled()\\n' + branch;")


def packing_workspace(program, tool_dx=None):
    """Rewire the original operator's blocks, keeping its mechanical values."""
    result = deepcopy(program)
    workspace = json.loads(result['blockly_json'])
    nodes = {}

    def walk(value):
        if isinstance(value, dict):
            if 'type' in value and 'id' in value:
                nodes[value['id']] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(workspace)
    if tool_dx is not None:
        import math
        tool_dx = float(tool_dx)
        if not math.isfinite(tool_dx) or tool_dx <= 0:
            raise ValueError('Measured symmetric tool X offset must be positive and finite')
        # Explicit operator measurement, not inferred from the packet/model.
        nodes['num_30']['fields']['NUM'] = tool_dx
        nodes['num_20']['fields']['NUM'] = 2 * tool_dx
    serial = 0

    def block(kind, fields=None, **inputs):
        nonlocal serial
        serial += 1
        item = {'type': kind, 'id': 'packing_fix_' + str(serial)}
        if fields is not None:
            item['fields'] = fields
        if inputs:
            item['inputs'] = {k: {'block': v} for k, v in inputs.items()}
        return item

    def get(name):
        return block('variables_get', {'VAR': {'id': 'var_' + name}})

    def num(value):
        return block('math_number', {'NUM': value})

    def setvar(name, value):
        return block('variables_set', {'VAR': {'id': 'var_' + name}}, VALUE=value)

    def arithmetic(op, a, b):
        return block('math_arithmetic', {'OP': op}, A=a, B=b)

    def floor(value):
        return block('math_round', {'OP': 'ROUNDDOWN'}, NUM=value)

    def mod(a, b):
        return block('math_modulo', DIVIDEND=a, DIVISOR=b)

    def chain(items):
        for a, b in zip(items, items[1:]):
            a['next'] = {'block': b}
        items[-1].pop('next', None)
        return items[0]

    def old_chain(start, end):
        items = []
        current = start
        while True:
            item = deepcopy(nodes[current])
            item.pop('next', None)
            items.append(item)
            if current == end:
                return chain(items)
            current = nodes[current]['next']['block']['id']

    def join(*heads):
        for a, b in zip(heads, heads[1:]):
            while 'next' in a:
                a = a['next']['block']
            a['next'] = {'block': b}
        return heads[0]

    def wait(timeout):
        # Mi_Goi is class 0 in the current model; don't collect other classes.
        return setvar('mi_goi', block('wait_object_in_robot_area', {'OBJECT_TYPE': '0'}, TIMEOUT_MS=timeout))

    def slot(head):
        suffix = str(head)
        def index():
            return get('PACKED_COUNT') if head == 0 else arithmetic('ADD', get('PACKED_COUNT'), num(1))
        return chain([
            setvar('col_index', mod(index(), get('COLS'))),
            setvar('row_index', mod(floor(arithmetic('DIVIDE', index(), get('COLS'))), get('ROWS'))),
            setvar('layer_index', floor(arithmetic('DIVIDE', index(), arithmetic('MULTIPLY', get('COLS'), get('ROWS'))))),
            setvar('place_x'+suffix, arithmetic('ADD', get('BOX_X'), arithmetic('MULTIPLY', get('col_index'), get('PITCH_X')))),
            setvar('place_y'+suffix, arithmetic('ADD', get('BOX_Y'), arithmetic('MULTIPLY', get('row_index'), get('PITCH_Y')))),
            setvar('place_z'+suffix, arithmetic('ADD', get('Z_PLACE'), arithmetic('MULTIPLY', get('layer_index'), get('LAYER_Z')))),
        ])

    def new_ids(value):
        nonlocal serial
        if isinstance(value, dict):
            if 'type' in value and 'id' in value:
                serial += 1
                value['id'] = 'packing_fix_' + str(serial)
            for child in value.values():
                new_ids(child)
        elif isinstance(value, list):
            for child in value:
                new_ids(child)
        return value

    def position(suffix):
        result = block('lists_create_with', ADD0=get('place_x'+suffix),
                       ADD1=get('place_y'+suffix), ADD2=get('place_z'+suffix))
        result['extraState'] = {'itemCount': 3}
        return result

    def single_place():
        math_chain = new_ids(old_chain('set_60', 'set_96'))
        prepare = chain([setvar('target_x', get('place_x0')), setvar('target_y', get('place_y0')),
                         setvar('use_angle', get('PLACE_ANGLE'))])
        call = block('move_place_xyangle', {'END_EFFECTOR_ID': '0', 'TRACKER_ID': 'None', 'SHOW_MOVEMENT': False},
                     X=get('tool_x'), Y=get('tool_y'), ANGLE=get('use_angle'),
                     Z_MOVE=get('Z_MOVE'), Z_PLACE=get('place_z0'))
        call['data'] = 'false'
        return join(prepare, math_chain, call,
                    setvar('PACKED_COUNT', arithmetic('ADD', get('PACKED_COUNT'), num(1))))

    for name in ['PACKED_COUNT', 'BOX_CAPACITY', 'SECOND_WAIT_MS', 'second_ready', 'pair_fits']:
        workspace['variables'].append({'id': 'var_' + name, 'name': name})
    initial = old_chain('home_1', 'set_layer_init')
    setup = chain([setvar('PACKED_COUNT', num(0)),
                   setvar('BOX_CAPACITY', block('packing_capacity', COLS=get('COLS'), ROWS=get('ROWS'), LAYERS=get('LAYERS'))),
                   setvar('SECOND_WAIT_MS', num(2000))])
    second_pick = join(old_chain('set_116', 'hold_167'), setvar('second_ready', block('logic_boolean', {'BOOL': 'TRUE'})))
    second_if = block('controls_if', IF0=get('mi_goi'), DO0=second_pick)
    has_room = block('logic_compare', {'OP': 'LT'}, A=arithmetic('ADD', get('PACKED_COUNT'), num(1)), B=get('BOX_CAPACITY'))
    can_collect = block('logic_operation', {'OP': 'AND'}, A=has_room, B=get('pair_fits'))
    collect_second = block('controls_if', IF0=can_collect, DO0=join(wait(get('SECOND_WAIT_MS')), second_if))
    # Preserve the operator's new midpoint/descent/release/lift block sequence.
    paired_place = join(old_chain('set_tool_mid_x', 'move_up_box'),
                        setvar('PACKED_COUNT', arithmetic('ADD', get('PACKED_COUNT'), num(2))))
    placement = block('controls_if', IF0=get('second_ready'), DO0=paired_place, ELSE=single_place())
    placement['extraState'] = {'hasElse': True}
    geometry = setvar('pair_fits', block('packing_pair_fits', FIRST=position('0'), SECOND=position('1'),
                                       ANGLE=get('PLACE_ANGLE'), DX=get('GRIP_DX'), DY=get('GRIP_DY')))
    body = join(slot(0), slot(1), geometry, wait(num(0)), old_chain('set_52', 'hold_103'),
                setvar('second_ready', block('logic_boolean', {'BOOL': 'FALSE'})),
                collect_second, placement)
    main = deepcopy(nodes['main_38'])
    main['inputs'] = {'BOOL': {'block': block('logic_compare', {'OP': 'LT'}, A=get('PACKED_COUNT'), B=get('BOX_CAPACITY'))},
                      'DO': {'block': body}}
    done = block('script_completion_message', MESSAGE=block('text', {'TEXT': 'Thùng đầy. Thay thùng rồi bấm Chạy lại để xếp thùng mới.'}))
    workspace['blocks']['blocks'] = [join(initial, setup, main, done)]
    result['blockly_json'] = json.dumps(workspace, ensure_ascii=False, separators=(',', ':'))
    # Never leave stale executable code paired with a changed workspace.
    result['code'] = ''
    return result


def build(baseline, output, tool_dx=None):
    baseline, output = Path(baseline), Path(output)
    patches = {
        'deltax_pp_sw/Pick.py': lambda s: patch_pick(s),
        'deltax_pp_sw/PythonScriptExecutor.py': lambda s: (HERE/'PythonScriptExecutor.py').read_text(encoding='utf8'),
        'deltax_pp_web/src/components/blockly/blocks/other-blocks.ts': patch_loops,
        'deltax_pp_web/src/components/blockly/BlocklyEditor.tsx': patch_editor,
    }
    entries = []
    for relative, patch in patches.items():
        original = (baseline/relative).read_bytes()
        updated = patch(original.decode('utf8')).encode('utf8')
        target = output/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(updated)
        entries.append({'path': relative, 'before_sha256': hashlib.sha256(original).hexdigest(),
                        'after_sha256': hashlib.sha256(updated).hexdigest()})
    rel = 'deltax_pp_web/src/components/blockly/blocks/packing-blocks.ts'
    target = output/rel
    target.write_bytes((HERE/'packing-blocks.ts').read_bytes())
    entries.append({'path': rel, 'before_sha256': None, 'after_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    rel = 'deltax_pp_sw/programs/blockly/MiGoi_XepThung.json'
    original = (baseline/rel).read_bytes()
    program = packing_workspace(json.loads(original), tool_dx=tool_dx)
    target = output/rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(program, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    entries.append({'path': rel, 'before_sha256': hashlib.sha256(original).hexdigest(), 'after_sha256': None})
    (output/'manifest.json').write_text(json.dumps({'files': entries}, indent=2), encoding='utf8')
    return entries


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline')
    parser.add_argument('output')
    parser.add_argument('--tool-dx', type=float, help='Explicitly measured offset on each side; grid X pitch becomes twice this value')
    args = parser.parse_args()
    build(args.baseline, args.output, tool_dx=args.tool_dx)
