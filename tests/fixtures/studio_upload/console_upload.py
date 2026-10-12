import binascii

class Console:
    def _cleanup_stale_rknn_upload_sessions(self, max_age_seconds=300):
        now = time.time()
        stale_ids = []
        with self._rknn_upload_sessions_lock:
            for upload_id, session in list(self._rknn_upload_sessions.items()):
                last_update = session.get('last_update', 0)
                if now - last_update > max_age_seconds:
                    stale_ids.append(upload_id)
            for upload_id in stale_ids:
                self._rknn_upload_sessions.pop(upload_id, None)

        for upload_id in stale_ids:
            print(f"RKNN upload session timeout cleanup: {upload_id}")


    def _emit_rknn_upload_chunk_ack(self, upload_id, file_name, chunk_index, total_chunks, status="ok", message="", received_chunks=None):
        payload = {
            "upload_id": upload_id,
            "file_name": file_name,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "status": status
        }
        if message:
            payload["message"] = message
        if received_chunks is not None:
            payload["received_chunks"] = received_chunks
        self.emitToServer("rknn_upload_chunk_ack", payload)


    def _emit_rknn_upload_progress(self, upload_id, file_name, progress, message, phase="uploading"):
        self.emitToServer("rknn_upload_progress", {
            "upload_id": upload_id,
            "file_name": file_name,
            "progress": int(max(0, min(100, progress))),
            "phase": phase,
            "message": message
        })


    def upload_rknn_file_chunk(self, data):
        if self.is_system_running:
            self._emit_rknn_upload_chunk_ack(
                str(data.get("upload_id", "")),
                str(data.get("file_name", "unknown")),
                int(data.get("chunk_index", -1)) if str(data.get("chunk_index", "")).lstrip("-").isdigit() else -1,
                int(data.get("total_chunks", 0)) if str(data.get("total_chunks", "")).isdigit() else 0,
                status="error",
                message="System is running, cannot upload model file"
            )
            return

        self._cleanup_stale_rknn_upload_sessions()

        upload_id = str(data.get("upload_id", "")).strip()
        file_name = str(data.get("file_name", "")).strip()
        chunk_data = data.get("chunk_data")

        try:
            chunk_index = int(data.get("chunk_index", -1))
            total_chunks = int(data.get("total_chunks", 0))
        except (TypeError, ValueError):
            self._emit_rknn_upload_chunk_ack(
                upload_id,
                file_name or "unknown",
                -1,
                0,
                status="error",
                message="Invalid chunk index or total chunks"
            )
            return

        if not upload_id or not file_name or not isinstance(chunk_data, str):
            self._emit_rknn_upload_chunk_ack(
                upload_id,
                file_name or "unknown",
                chunk_index,
                total_chunks,
                status="error",
                message="Missing upload_id, file_name, or chunk_data"
            )
            return

        if total_chunks <= 0 or chunk_index < 0 or chunk_index >= total_chunks:
            self._emit_rknn_upload_chunk_ack(
                upload_id,
                file_name,
                chunk_index,
                total_chunks,
                status="error",
                message="Chunk index out of range"
            )
            return

        should_finalize = False
        ack_status = "ok"
        with self._rknn_upload_sessions_lock:
            session = self._rknn_upload_sessions.get(upload_id)
            if session is None:
                session = {
                    "file_name": file_name,
                    "total_chunks": total_chunks,
                    "chunks": {},
                    "received_chunks": 0,
                    "processing": False,
                    "completed": False,
                    "last_update": time.time()
                }
                self._rknn_upload_sessions[upload_id] = session
            else:
                if session.get("file_name") != file_name or int(session.get("total_chunks", -1)) != total_chunks:
                    self._emit_rknn_upload_chunk_ack(
                        upload_id,
                        file_name,
                        chunk_index,
                        total_chunks,
                        status="error",
                        message="Upload session mismatch (file name or chunk count changed)"
                    )
                    return

            if session.get("completed", False):
                self._emit_rknn_upload_chunk_ack(
                    upload_id,
                    file_name,
                    chunk_index,
                    total_chunks,
                    status="done",
                    received_chunks=session.get("received_chunks", 0)
                )
                return

            if chunk_index in session["chunks"]:
                ack_status = "duplicate"
            else:
                session["chunks"][chunk_index] = chunk_data
                session["received_chunks"] += 1

            session["last_update"] = time.time()
            received_chunks = int(session["received_chunks"])

            if received_chunks >= total_chunks and not session.get("processing", False):
                session["processing"] = True
                should_finalize = True

        self._emit_rknn_upload_chunk_ack(
            upload_id,
            file_name,
            chunk_index,
            total_chunks,
            status=ack_status,
            received_chunks=received_chunks
        )

        progress = int((received_chunks / total_chunks) * 100)
        self._emit_rknn_upload_progress(
            upload_id,
            file_name,
            progress,
            f"Received {received_chunks}/{total_chunks} chunks",
            phase="uploading"
        )

        if should_finalize:
            threading.Thread(target=self._process_rknn_upload_session, args=(upload_id,), daemon=True).start()


    def upload_rknn_file_finalize(self, data):
        upload_id = str(data.get("upload_id", "")).strip()
        if not upload_id:
            self.emitToServer("rknn_upload_response", {
                "status": "error",
                "message": "Missing upload_id for finalize",
                "file_name": "unknown",
                "upload_id": ""
            })
            return

        should_finalize = False
        with self._rknn_upload_sessions_lock:
            session = self._rknn_upload_sessions.get(upload_id)
            if session is None:
                self.emitToServer("rknn_upload_response", {
                    "status": "error",
                    "message": "Upload session not found during finalize",
                    "file_name": "unknown",
                    "upload_id": upload_id
                })
                return

            if not session.get("processing", False) and not session.get("completed", False):
                session["processing"] = True
                should_finalize = True

        if should_finalize:
            threading.Thread(target=self._process_rknn_upload_session, args=(upload_id,), daemon=True).start()


    def _save_rknn_model_bytes(self, file_name, file_data):
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
        os.makedirs(models_dir, exist_ok=True)

        safe_file_name = os.path.basename(str(file_name))
        if not safe_file_name.lower().endswith('.rknn'):
            safe_file_name = f"{safe_file_name}.rknn"

        file_path = os.path.join(models_dir, safe_file_name)
        tmp_file_path = f"{file_path}.tmp"

        with open(tmp_file_path, 'wb') as f:
            f.write(file_data)

        os.replace(tmp_file_path, file_path)
        print(f"RKNN file saved: {file_path}")

        model_name = os.path.splitext(safe_file_name)[0]
        if model_name not in self.system_settings['aix']['list_models']:
            self.system_settings['aix']['list_models'].append(model_name)

        return model_name


    def _process_rknn_upload_session(self, upload_id):
        session = None
        try:
            with self._rknn_upload_sessions_lock:
                session = self._rknn_upload_sessions.get(upload_id)
                if session is None:
                    return

                file_name = session.get("file_name", "unknown.rknn")
                total_chunks = int(session.get("total_chunks", 0))
                chunks = session.get("chunks", {})

            if total_chunks <= 0:
                raise Exception("Invalid total_chunks in upload session")

            missing_chunks = [i for i in range(total_chunks) if i not in chunks]
            if missing_chunks:
                raise Exception(f"Missing chunks: {len(missing_chunks)}")

            self._emit_rknn_upload_progress(
                upload_id,
                file_name,
                95,
                "All chunks received, decoding and saving model...",
                phase="processing"
            )

            ordered_base64 = ''.join(chunks[i] for i in range(total_chunks))
            try:
                file_data = base64.b64decode(ordered_base64, validate=True)
            except binascii.Error as decode_error:
                raise Exception(f"Invalid base64 upload data: {decode_error}")

            model_name = self._save_rknn_model_bytes(file_name, file_data)

            with self._rknn_upload_sessions_lock:
                current_session = self._rknn_upload_sessions.get(upload_id)
                if current_session is not None:
                    current_session["completed"] = True

            self._emit_rknn_upload_progress(
                upload_id,
                file_name,
                100,
                "Upload completed",
                phase="done"
            )

            self.emitToServer("rknn_upload_response", {
                "status": "success",
                "message": f"File {file_name} uploaded successfully",
                "file_name": model_name,
                "upload_id": upload_id
            })

        except Exception as e:
            file_name = "unknown.rknn"
            if isinstance(session, dict):
                file_name = str(session.get("file_name", file_name))
            model_name = os.path.splitext(file_name)[0] if file_name else "unknown"

            print(f"Error processing RKNN chunk upload: {str(e)}")
            self._emit_rknn_upload_progress(
                upload_id,
                file_name,
                0,
                f"Upload failed: {str(e)}",
                phase="error"
            )
            self.emitToServer("rknn_upload_response", {
                "status": "error",
                "message": str(e),
                "file_name": model_name,
                "upload_id": upload_id
            })

        finally:
            with self._rknn_upload_sessions_lock:
                self._rknn_upload_sessions.pop(upload_id, None)


    def _process_rknn_upload(self, data):
        """Process RKNN file upload in a separate thread

        Args:
            data (dict): Dictionary containing file_name and file_data
        """
        try:
            file_name = data.get('file_name')
            file_data_base64 = data.get('file_data')

            if not file_name or not file_data_base64:
                self.emitToServer("rknn_upload_response", {
                    "status": "error",
                    "message": "Missing filename or file data",
                    "file_name": file_name or 'unknown'
                })
                return

            print(f"Decoding base64 data for file: {file_name}")
            file_data = base64.b64decode(file_data_base64, validate=True)
            model_name = self._save_rknn_model_bytes(file_name, file_data)

            # Send success response
            self.emitToServer("rknn_upload_response", {
                "status": "success",
                "message": f"File {file_name} uploaded successfully",
                "file_name": model_name
            })

        except Exception as e:
            print(f"Error saving RKNN file: {str(e)}")
            # Extract model name from file_name even in error case
            model_name = os.path.splitext(data.get('file_name', 'unknown'))[0] if data.get('file_name') else 'unknown'
            self.emitToServer("rknn_upload_response", {
                "status": "error",
                "message": str(e),
                "file_name": model_name
            })

    def delete_model(self, data):
        """Handle model deletion request from NextJS client

        Args:
            data (dict): Dictionary containing:
                - model_name: Name of the model to delete (without extension)
        """
        if self.is_system_running:
            self.emitToServer("delete_model_response", {
                "status": "error",
                "message": "System is running, cannot delete model file",
                "model_name": data.get('model_name', 'unknown')
            })
            return

        self.aix_delete_model_signal.emit(data.get('model_name', 'unknown'))
        self.emitToServer("delete_model_response", {
            "status": "success",
            "message": f"Model {data.get('model_name', 'unknown')} deleted successfully"
        })
