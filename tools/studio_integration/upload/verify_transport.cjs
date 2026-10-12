// Run the real generated hook in a browser/socket harness, including retry and cleanup.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(process.argv[2], 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
}, reportDiagnostics: true });
assert.equal(compiled.diagnostics.length, 0);

async function scenario(mode) {
  const listeners = new Map();
  const pendingTimers = new Set();
  const chunks = [];
  let finalizedPayload;
  let missedAck = false;
  const socket = {
    connected: mode !== 'disconnected',
    on(name, callback) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(callback); },
    off(name, callback) { listeners.get(name)?.delete(callback); },
    emit(name, data) { for (const cb of [...(listeners.get(name) ?? [])]) cb(data); },
  };
  const service = { socket,
    upload_rknn_file_chunk(payload) {
      assert.equal(payload.upload_contract, 'paired-v1');
      chunks.push(payload);
      socket.emit('rknn_upload_progress', { upload_id: 'someone-else', progress: 91 });
      socket.emit('rknn_upload_progress', { upload_id: payload.upload_id, progress: 50 });
      socket.emit('rknn_upload_response', { upload_id: 'someone-else', status: 'success', file_name: 'model' });
      if (mode === 'retry' && !missedAck) { missedAck = true; return; }
      socket.emit('rknn_upload_chunk_ack', { ...payload, status: mode === 'retry' ? 'duplicate' : 'ok' });
    },
    upload_rknn_file_finalize(payload) {
      finalizedPayload = payload;
      if (mode === 'timeout') return;
      socket.emit('rknn_upload_response', { upload_id: payload.upload_id, file_name: 'model',
        status: mode === 'error' ? 'error' : 'success', message: 'server rejection',
        metadata: { task: 'ori', names: { '0': 'part' } } });
    },
  };
  const module = { exports: {} };
  class FileReader {
    readAsDataURL() { queueMicrotask(() => this.onload({ target: { result: 'data:application/octet-stream;base64,' + 'A'.repeat(140000) } })); }
  }
  const timed = (callback) => {
    const timer = setTimeout(() => { pendingTimers.delete(timer); callback(); }, 2);
    pendingTimers.add(timer);
    return timer;
  };
  vm.runInNewContext(compiled.outputText, {
    exports: module.exports, module, FileReader, Math, Date,
    require(name) {
      if (name === 'react') return { useCallback: fn => fn };
      if (name.includes('socketService')) return { __esModule: true, default: service };
      return {};
    },
    window: { setTimeout: timed, clearTimeout(timer) { clearTimeout(timer); pendingTimers.delete(timer); } },
    setTimeout: timed,
  });
  const progress = [];
  const upload = module.exports.useSocket().uploadRknnFile;
  const promise = upload({ name: 'model.rknn' }, '{"task":"ori"}', true, data => progress.push(data.progress));
  if (['error', 'timeout', 'disconnected'].includes(mode)) {
    await assert.rejects(promise, mode === 'error' ? /server rejection/ : mode === 'timeout' ? /Finalize timeout/ : /not connected/);
  } else {
    const result = await promise;
    assert.equal(result.file_name, 'model');
    assert.deepEqual(JSON.parse(JSON.stringify(result.metadata.names)), { '0': 'part' });
  }
  if (mode !== 'disconnected') {
    assert.equal(finalizedPayload.metadata_json, '{"task":"ori"}');
    assert.equal(finalizedPayload.require_metadata, true);
    assert.equal(chunks.length, mode === 'retry' ? 3 : 2);
    assert.ok(progress.every(value => value === 50));
  }
  assert.equal([...listeners.values()].reduce((sum, set) => sum + set.size, 0), 0, 'all response/progress/ACK listeners removed');
  assert.equal(pendingTimers.size, 0, 'all timers cleared, including synchronous finalize replies');
  console.log('TRANSPORT_OK', mode);
}
(async () => { for (const mode of ['success', 'retry', 'error', 'timeout', 'disconnected']) await scenario(mode); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
