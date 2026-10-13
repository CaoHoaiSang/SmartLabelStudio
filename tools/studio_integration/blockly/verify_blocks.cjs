// Check actual new block definitions with the audited Blockly generator.
const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');
const ts = require('typescript');
const Blockly = require('blockly');
require('blockly/blocks');
const { pythonGenerator } = require('blockly/python');
console.warn = (...args) => { throw new Error(args.join(' ')); };
const source = fs.readFileSync(__dirname + '/packing-blocks.ts', 'utf8');
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
}).outputText;
vm.runInThisContext('(function(require,module,exports){' + code + '\n})')(require, { exports: {} }, {});
Blockly.Events.disable();
const workspace = new Blockly.Workspace();
const number = value => ({ type: 'math_number', fields: { NUM: value } });
const value = block => ({ block });
Blockly.serialization.workspaces.load({
  blocks: { languageVersion: 0, blocks: [
    { type: 'variables_set', fields: { VAR: { id: 'object' } }, inputs: { VALUE: value({
      type: 'wait_object_in_robot_area', fields: { OBJECT_TYPE: '0' }, inputs: { TIMEOUT_MS: value(number(2000)) }
    }) } },
    { type: 'variables_set', fields: { VAR: { id: 'capacity' } }, inputs: { VALUE: value({
      type: 'packing_capacity', inputs: { COLS: value(number(3)), ROWS: value(number(1)), LAYERS: value(number(1)) }
    }) } },
    { type: 'script_completion_message', inputs: { MESSAGE: value({ type: 'text', fields: { TEXT: 'Thùng đầy' } }) } },
    { type: 'variables_set', fields: { VAR: { id: 'layer' } }, inputs: { VALUE: value({
      type: 'math_round', fields: { OP: 'ROUNDDOWN' }, inputs: { NUM: value(number(1.75)) }
    }) } },
    { type: 'variables_set', fields: { VAR: { id: 'fits' } }, inputs: { VALUE: value({
      type: 'packing_pair_fits', inputs: {
        FIRST: value({ type: 'lists_create_with', extraState: { itemCount: 3 }, inputs: { ADD0: value(number(0)), ADD1: value(number(0)), ADD2: value(number(-650)) } }),
        SECOND: value({ type: 'lists_create_with', extraState: { itemCount: 3 }, inputs: { ADD0: value(number(126)), ADD1: value(number(0)), ADD2: value(number(-650)) } }),
        ANGLE: value(number(0)), DX: value(number(63)), DY: value(number(0))
      }
    }) } }
  ] },
  variables: [{ name: 'object', id: 'object' }, { name: 'capacity', id: 'capacity' }, { name: 'layer', id: 'layer' }, { name: 'fits', id: 'fits' }]
}, workspace);
const generated = pythonGenerator.workspaceToCode(workspace);
assert(generated.includes('pick.wait_object_in_robot_area(object_type=0, timeout_ms=2000)'));
assert(generated.includes('pick.packing_capacity(3, 1, 1)'));
assert(generated.includes("pick.set_script_completion_message('Thùng đầy')"));
assert(generated.includes('math.floor(1.75)'));
assert(generated.includes('pick.packing_pair_fits([0, 0, -650], [126, 0, -650], 0, 63, 0)'));
const saved = Blockly.serialization.workspaces.save(workspace);
const roundtrip = new Blockly.Workspace();
Blockly.serialization.workspaces.load(saved, roundtrip);
assert.equal(pythonGenerator.workspaceToCode(roundtrip), generated);
workspace.dispose(); roundtrip.dispose();
console.log('Packing Blockly definitions, class/timeout fields, floor and save/load passed.');
