import * as Blockly from 'blockly';
import { pythonGenerator, Order } from 'blockly/python';

Blockly.Blocks['packing_pair_fits'] = {
  init: function(this: Blockly.Block) {
    for (const [name, label] of [['FIRST', 'Đặt chung một lần · Ô 1 [X,Y,Z]'],
      ['SECOND', 'Ô 2 [X,Y,Z]'], ['ANGLE', 'Góc đặt'], ['DX', 'Offset X mỗi đầu ±'], ['DY', 'Offset Y mỗi đầu ±']]) {
      this.appendValueInput(name).setCheck(name === 'FIRST' || name === 'SECOND' ? 'Array' : 'Number').appendField(label);
    }
    this.setOutput(true, 'Boolean');
    this.setColour(210);
    this.setTooltip('Hai ô phải cùng cao độ và khớp khoảng cách hai đầu hút tại góc đặt.');
  }
};
pythonGenerator.forBlock['packing_pair_fits'] = function(block: Blockly.Block) {
  const values = ['FIRST', 'SECOND', 'ANGLE', 'DX', 'DY'].map(name =>
    pythonGenerator.valueToCode(block, name, Order.NONE) || (name === 'FIRST' || name === 'SECOND' ? '[]' : '0'));
  return [`pick.packing_pair_fits(${values.join(', ')})`, Order.FUNCTION_CALL];
};

Blockly.Blocks['packing_capacity'] = {
  init: function(this: Blockly.Block) {
    for (const [name, label] of [['COLS', 'Sức chứa thùng · Cột'], ['ROWS', 'Hàng'], ['LAYERS', 'Tầng']]) {
      this.appendValueInput(name).setCheck('Number').appendField(label);
    }
    this.setOutput(true, 'Number');
    this.setColour(210);
    this.setTooltip('Cột × hàng × tầng. Mỗi giá trị phải là số nguyên dương.');
  }
};
pythonGenerator.forBlock['packing_capacity'] = function(block: Blockly.Block) {
  const values = ['COLS', 'ROWS', 'LAYERS'].map(name => pythonGenerator.valueToCode(block, name, Order.NONE) || '0');
  return [`pick.packing_capacity(${values.join(', ')})`, Order.FUNCTION_CALL];
};

Blockly.Blocks['wait_object_in_robot_area'] = {
  init: function(this: Blockly.Block) {
    this.appendDummyInput()
      .appendField('Chờ vật trong vùng robot · Loại')
      .appendField(new Blockly.FieldDropdown([
        ['Mọi loại', 'None'], ...Array.from({ length: 9 }, (_, i): [string, string] => [String(i), String(i)])
      ]), 'OBJECT_TYPE');
    this.appendValueInput('TIMEOUT_MS').setCheck('Number')
      .appendField('Thời gian chờ (ms, 0 = không giới hạn)');
    this.setOutput(true, null);
    this.setColour(210);
    this.setTooltip('Trả về vật hoặc None khi hết thời gian. Stop hủy chương trình đang chạy.');
  }
};
pythonGenerator.forBlock['wait_object_in_robot_area'] = function(block: Blockly.Block) {
  const timeout = pythonGenerator.valueToCode(block, 'TIMEOUT_MS', Order.NONE) || '0';
  return [`pick.wait_object_in_robot_area(object_type=${block.getFieldValue('OBJECT_TYPE')}, timeout_ms=${timeout})`, Order.FUNCTION_CALL];
};

Blockly.Blocks['script_completion_message'] = {
  init: function(this: Blockly.Block) {
    this.appendValueInput('MESSAGE').setCheck('String').appendField('Thông báo khi chương trình hoàn tất');
    this.setPreviousStatement(true, null);
    this.setNextStatement(true, null);
    this.setColour(160);
    this.setTooltip('Đặt thông báo hoàn tất; các block phía sau vẫn chạy nếu có.');
  }
};
pythonGenerator.forBlock['script_completion_message'] = function(block: Blockly.Block) {
  const message = pythonGenerator.valueToCode(block, 'MESSAGE', Order.NONE) || "''";
  return `pick.set_script_completion_message(${message})\n`;
};
