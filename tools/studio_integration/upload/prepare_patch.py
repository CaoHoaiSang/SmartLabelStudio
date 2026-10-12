"""Prepare checksum-pinned upload patches from the operator's actual Studio source.

No file in the input checkouts is changed. Review/apply the generated manifest.
Unrecognized anchors fail rather than replacing unrelated Studio modifications.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Studio source changed; review anchor: {old[:100]!r}")
    return source.replace(old, new, 1)


def replace_method(source, name, new):
    methods = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(methods) != 1:
        raise ValueError(f"Expected one Console.{name}")
    node = methods[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [new.rstrip() + "\n"]
    return "".join(lines)


def console_patch(source):
    source = replace_once(source, "import binascii\n", "import binascii\nfrom rknn_model_upload import save_model_pair\n")
    source = replace_once(source, '"file_name": file_name,\n                    "total_chunks": total_chunks,',
                          '"file_name": file_name,\n                    "upload_contract": data.get("upload_contract"),\n                    "total_chunks": total_chunks,')
    source = replace_once(source, 'if session.get("file_name") != file_name or int(session.get("total_chunks", -1)) != total_chunks:',
                          'if (session.get("file_name") != file_name or int(session.get("total_chunks", -1)) != total_chunks\n                        or session.get("upload_contract") != data.get("upload_contract")):')
    source = replace_once(source, 'if received_chunks >= total_chunks and not session.get("processing", False):',
                          'if (received_chunks >= total_chunks and not session.get("processing", False)\n                    and session.get("upload_contract") != "paired-v1"):')
    source = replace_method(source, 'upload_rknn_file_finalize', '''    def upload_rknn_file_finalize(self, data):
        upload_id = str(data.get("upload_id", "")).strip()
        try:
            if self.is_system_running:
                raise ValueError("System is running, cannot upload model file")
            with self._rknn_upload_sessions_lock:
                session = self._rknn_upload_sessions.get(upload_id)
                if session is None:
                    raise ValueError("Upload session not found during finalize")
                if (data.get("file_name") != session["file_name"]
                        or data.get("total_chunks") != session["total_chunks"]):
                    raise ValueError("Upload finalize does not match file/chunk count")
                if session.get("processing") or session.get("completed"):
                    return
                if session["received_chunks"] != session["total_chunks"]:
                    raise ValueError("Upload is incomplete")
                metadata = data.get("metadata_json")
                if metadata is not None and (not isinstance(metadata, str) or len(metadata.encode("utf-8")) > 65536):
                    raise ValueError("Model JSON must be text smaller than 64 KiB")
                if data.get("require_metadata") and metadata is None:
                    raise ValueError("ORI upload requires its exported JSON file")
                session["metadata_json"] = metadata
                session["processing"] = True
            threading.Thread(target=self._process_rknn_upload_session, args=(upload_id,), daemon=True).start()
        except (ValueError, TypeError, KeyError) as exc:
            self.emitToServer("rknn_upload_response", {
                "status": "error", "message": str(exc),
                "file_name": os.path.splitext(str(data.get("file_name", "unknown")))[0],
                "upload_id": upload_id
            })
''')
    source = replace_method(source, '_save_rknn_model_bytes', '''    def _save_rknn_model_bytes(self, file_name, file_data, metadata_json=None):
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
        model_name, metadata = save_model_pair(
            models_dir, file_name, file_data, metadata_json,
            can_save=lambda: not self.is_system_running)
        if model_name not in self.system_settings['aix']['list_models']:
            self.system_settings['aix']['list_models'].append(model_name)
        return model_name, metadata
''')
    source = replace_once(source, 'model_name = self._save_rknn_model_bytes(file_name, file_data)\n\n            with',
                          'model_name, metadata = self._save_rknn_model_bytes(file_name, file_data, session.get("metadata_json"))\n\n            with')
    source = replace_once(source, '"file_name": model_name,\n                "upload_id": upload_id\n            })\n\n        except',
                          '"file_name": model_name,\n                "metadata": metadata,\n                "upload_id": upload_id\n            })\n\n        except')
    source = replace_once(source, 'model_name = self._save_rknn_model_bytes(file_name, file_data)',
                          'model_name, metadata = self._save_rknn_model_bytes(file_name, file_data, data.get("metadata_json"))')
    source = replace_once(source, '"message": f"File {file_name} uploaded successfully",\n                "file_name": model_name\n',
                          '"message": f"File {file_name} uploaded successfully",\n                "file_name": model_name,\n                "metadata": metadata\n')
    ast.parse(source)
    return source


def hook_patch(source):
    source = replace_once(source, 'const uploadRknnFile = useCallback((file: File) => {\n    return new Promise<void>',
                          'const uploadRknnFile = useCallback((file: File, metadataJson?: string, requireMetadata = false, onProgress?: (data: { progress?: number; message?: string; phase?: string }) => void) => {\n    return new Promise<{ file_name: string; metadata?: { task: string; names: Record<string, string> } } >')
    source = replace_once(source, '        const cleanup = () => {', '''        let progressHandler: ((data: any) => void) | null = null;
        const cleanup = () => {
          if (progressHandler) {
            socket.off('rknn_upload_progress', progressHandler);
            progressHandler = null;
          }''')
    source = replace_once(source, "          socket.on('rknn_upload_response', finalResponseHandler);", '''          socket.on('rknn_upload_response', finalResponseHandler);
          progressHandler = (data: any) => {
            if (data?.upload_id === uploadId) onProgress?.(data);
          };
          socket.on('rknn_upload_progress', progressHandler);''')
    source = replace_once(source, "              resolve();", "              resolve(data);")
    source = replace_once(source, '                  chunk_data: chunkData\n', '                  chunk_data: chunkData,\n                  upload_contract: "paired-v1"\n')
    source = replace_once(source, '            total_chunks: totalChunks\n          });',
                          '            total_chunks: totalChunks,\n            metadata_json: metadataJson,\n            require_metadata: requireMetadata\n          });')
    source = replace_once(source, '            await sendChunkWithRetry(chunkIndex, chunkData);',
                          '            await sendChunkWithRetry(chunkIndex, chunkData);\n            if (finalized) return;')
    # Install the timeout before emitting finalize; even a synchronous response cleans it.
    start = source.index('          socketService.upload_rknn_file_finalize({')
    stop = source.index('          }, finalizeTimeoutMs);', start) + len('          }, finalizeTimeoutMs);')
    block = source[start:stop]
    split = block.index('          finalizeTimeoutId =')
    source = source[:start] + block[split:] + '\n\n' + block[:split].rstrip() + source[stop:]
    return source


def socket_patch(source):
    source = replace_once(source, '    chunk_data: string;\n', '    chunk_data: string;\n    upload_contract?: "paired-v1";\n')
    source = replace_once(source, 'public upload_rknn_file_finalize = (payload: {\n    upload_id: string;\n    file_name: string;\n    total_chunks: number;',
                          'public upload_rknn_file_finalize = (payload: {\n    upload_id: string;\n    file_name: string;\n    total_chunks: number;\n    metadata_json?: string;\n    require_metadata?: boolean;')
    return source


def vision_patch(source):
    source = replace_once(source, '    const [isUploading, setIsUploading]',
                          '    const [selectedModelJson, setSelectedModelJson] = useState<File | null>(null);\n    const [uploadedOri, setUploadedOri] = useState<{ model: string; names: string[] } | null>(null);\n    const metadataInputRef = useRef<HTMLInputElement>(null);\n    const [isUploading, setIsUploading]')
    start = source.index('        // Listen for RKNN file upload responses\n')
    end = source.index('        const removeDeleteModelListener', start)
    source = source[:start] + source[end:]
    source = replace_once(source, '            removeRknnUploadListener();\n', '')
    source = replace_once(source, '            removeRknnUploadProgressListener();\n', '')
    source = replace_once(source, "            if (file.name.endsWith('.rknn')) {", "            if (file.name.toLowerCase().endsWith('.rknn')) {")
    source = replace_once(source, '                setSelectedRknnFile(file);',
                          '                setSelectedRknnFile(file);\n                setSelectedModelJson(null);\n                setUploadedOri(null);\n                if (metadataInputRef.current) metadataInputRef.current.value = "";')
    source = replace_once(source, '            await socket.uploadRknnFile(selectedRknnFile);\n            // The actual success/failure will be handled by the socket response listener', '''            const requiresMetadata = systemSettingsRef.current.aix.model_type === 'ORI';
            if (requiresMetadata && !selectedModelJson) {
                throw new Error('Select the JSON file exported with this ORI model');
            }
            let metadataJson: string | undefined;
            if (selectedModelJson) {
                if (selectedModelJson.size > 65536) throw new Error('Model JSON must be smaller than 64 KiB');
                metadataJson = await selectedModelJson.text();
                const parsed = JSON.parse(metadataJson);
                if (parsed?.task !== 'ori') throw new Error('Select the ORI JSON exported by SmartLabel');
            }
            setUploadedOri(null);
            const result = await socket.uploadRknnFile(selectedRknnFile, metadataJson, requiresMetadata, data => {
                if (typeof data.progress === 'number') setUploadProgress(Math.max(0, Math.min(100, data.progress)));
                if (data.message) setUploadStatus({ status: 'uploading', message: data.message });
            });
            setUploadProgress(100);
            setUploadStatus({ status: 'success', message: 'Model uploaded successfully' });
            const current = systemSettingsRef.current;
            if (!current.aix.list_models.includes(result.file_name)) {
                setSystemSettingsRef.current({ ...current, aix: {
                    ...current.aix, list_models: [...current.aix.list_models, result.file_name]
                }});
            }
            if (result.metadata?.task === 'ori') {
                const names = result.metadata.names;
                setUploadedOri({ model: result.file_name, names: Object.keys(names)
                    .sort((a, b) => Number(a) - Number(b)).map(key => names[key]) });
            }
            setSelectedRknnFile(null);
            setSelectedModelJson(null);
            if (fileInputRef.current) fileInputRef.current.value = '';
            if (metadataInputRef.current) metadataInputRef.current.value = '';
            setIsUploading(false);''')
    source = replace_once(source, '                                    accept=".rknn"\n', '                                    accept=".rknn"\n                                    disabled={isUploading}\n                                    aria-label="RKNN model file"\n')
    source = replace_once(source, '                            {selectedRknnFile && (', '''                            <div className="mt-2 flex flex-wrap items-center gap-2">
                                <label htmlFor="ori-model-json" className="text-sm text-gray-700">Model JSON (required for ORI):</label>
                                <input id="ori-model-json" ref={metadataInputRef} type="file" accept=".json"
                                    disabled={isUploading || !selectedRknnFile}
                                    onChange={event => { setSelectedModelJson(event.target.files?.[0] ?? null); setUploadStatus(null); }}
                                    className="p-2 rounded-lg border border-gray-300 text-sm text-black max-w-full" />
                            </div>
                            {uploadedOri && (
                                <div className="mt-2 text-sm text-gray-700">
                                    <div>ORI model: {uploadedOri.model} · Classes: {uploadedOri.names.join(', ')}</div>
                                    <button type="button" className="mt-1 rounded-lg bg-blue-500 px-3 py-2 text-white"
                                        disabled={isUploading}
                                        onClick={() => {
                                            const current = systemSettingsRef.current;
                                            setSystemSettingsRef.current({ ...current, aix: { ...current.aix,
                                                project_name: uploadedOri.model, model_type: 'ORI',
                                                list_objects: uploadedOri.names.join(','), class_confidence_map: {}
                                            }});
                                            socket.pushNotification('ORI model and classes selected. Save settings to apply.');
                                        }}>Use this ORI model</button>
                                </div>
                            )}
                            {selectedRknnFile && (''')
    return source


def prepare(backend_root, web_root, output):
    output = Path(output)
    files = []
    payloads = {}
    plans = [('backend', Path(backend_root), 'Console.py', console_patch),
             ('web', Path(web_root), 'src/hooks/useSocket.ts', hook_patch),
             ('web', Path(web_root), 'src/api/socketService.tsx', socket_patch),
             ('web', Path(web_root), 'src/components/SystemComponents/Vision/VisionSettings.tsx', vision_patch)]
    for profile, root, relative, transform in plans:
        original = (root / relative).read_bytes()
        changed = transform(original.decode('utf-8').replace('\r\n', '\n')).encode('utf-8')
        payload = f'{profile}/{relative}'
        payloads[payload] = changed
        files.append(dict(profile=profile, path=relative, payload=payload,
                          before_sha256=hashlib.sha256(original).hexdigest(), after_sha256=hashlib.sha256(changed).hexdigest()))
    helper = Path(__file__).with_name('rknn_model_upload.py').read_bytes()
    payloads['backend/rknn_model_upload.py'] = helper
    files.append(dict(profile='backend', path='rknn_model_upload.py', payload='backend/rknn_model_upload.py',
                      before_sha256=None, after_sha256=hashlib.sha256(helper).hexdigest()))
    output.mkdir(parents=True, exist_ok=False)
    for relative, contents in payloads.items():
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(contents)
    (output / 'manifest.json').write_text(json.dumps({'files': files}, indent=2) + '\n', encoding='utf-8')
    return files


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend-root', required=True)
    parser.add_argument('--web-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    prepare(args.backend_root, args.web_root, args.output)
