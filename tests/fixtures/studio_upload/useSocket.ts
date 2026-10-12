import { useCallback } from 'react';
import socketService from './socketService';
export const useSocket = () => {
  const uploadRknnFile = useCallback((file: File) => {
    return new Promise<void>((resolve, reject) => {
      const socket = socketService.socket;
      if (!socket.connected) {
        reject(new Error('Socket is not connected'));
        return;
      }

      const reader = new FileReader();
      reader.onload = async (event) => {
        let finalResponseHandler: ((data: any) => void) | null = null;
        let finalizeTimeoutId: number | null = null;
        const cleanup = () => {
          if (finalResponseHandler) {
            socket.off('rknn_upload_response', finalResponseHandler);
            finalResponseHandler = null;
          }
          if (finalizeTimeoutId !== null) {
            window.clearTimeout(finalizeTimeoutId);
            finalizeTimeoutId = null;
          }
        };

        try {
          if (!event.target || !event.target.result) {
            throw new Error('Failed to read file');
          }

          const base64String = event.target.result as string;
          const base64Data = base64String.includes('base64,')
            ? base64String.split('base64,')[1]
            : base64String;

          const chunkSize = 128 * 1024; // base64 chars per chunk
          const maxRetries = 7;
          const ackTimeoutMs = 7000;
          const retryDelayMs = 500;
          const finalizeTimeoutMs = 60000;
          const totalChunks = Math.max(1, Math.ceil(base64Data.length / chunkSize));
          const uploadId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
          const expectedModelName = file.name.replace(/\.rknn$/i, '');

          let finalized = false;
          finalResponseHandler = (data: any) => {
            if (!data) {
              return;
            }

            if (data.upload_id && data.upload_id !== uploadId) {
              return;
            }

            if (!data.upload_id && data.file_name !== expectedModelName) {
              return;
            }

            if (data.status === 'success') {
              finalized = true;
              cleanup();
              resolve();
            } else if (data.status === 'error') {
              finalized = true;
              cleanup();
              reject(new Error(data.message || 'Upload failed'));
            }
          };

          socket.on('rknn_upload_response', finalResponseHandler);

          const sendChunkWithRetry = async (chunkIndex: number, chunkData: string) => {
            let lastError: Error | null = null;

            for (let attempt = 1; attempt <= maxRetries; attempt++) {
              const ackResult = await new Promise<{ ok: boolean; message?: string }>((ackResolve) => {
                let timeoutId: number | null = null;
                const ackHandler = (ack: any) => {
                  if (!ack || ack.upload_id !== uploadId || ack.chunk_index !== chunkIndex) {
                    return;
                  }

                  if (timeoutId !== null) {
                    window.clearTimeout(timeoutId);
                  }
                  socket.off('rknn_upload_chunk_ack', ackHandler);

                  if (ack.status === 'ok' || ack.status === 'duplicate' || ack.status === 'done') {
                    ackResolve({ ok: true });
                  } else {
                    ackResolve({ ok: false, message: ack.message || 'Chunk upload rejected by server' });
                  }
                };

                timeoutId = window.setTimeout(() => {
                  socket.off('rknn_upload_chunk_ack', ackHandler);
                  ackResolve({ ok: false, message: `Chunk ${chunkIndex + 1} ack timeout` });
                }, ackTimeoutMs);

                socket.on('rknn_upload_chunk_ack', ackHandler);
                socketService.upload_rknn_file_chunk({
                  upload_id: uploadId,
                  file_name: file.name,
                  chunk_index: chunkIndex,
                  total_chunks: totalChunks,
                  chunk_data: chunkData
                });
              });

              if (ackResult.ok) {
                return;
              }

              lastError = new Error(ackResult.message || `Chunk ${chunkIndex + 1} failed`);
              if (attempt < maxRetries) {
                await new Promise((r) => setTimeout(r, retryDelayMs));
              }
            }

            throw (lastError ?? new Error(`Chunk ${chunkIndex + 1} failed`));
          };

          for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
            const start = chunkIndex * chunkSize;
            const end = Math.min(base64Data.length, start + chunkSize);
            const chunkData = base64Data.slice(start, end);
            await sendChunkWithRetry(chunkIndex, chunkData);
          }

          socketService.upload_rknn_file_finalize({
            upload_id: uploadId,
            file_name: file.name,
            total_chunks: totalChunks
          });

          finalizeTimeoutId = window.setTimeout(() => {
            if (!finalized) {
              cleanup();
              reject(new Error('Finalize timeout while waiting for server response'));
            }
          }, finalizeTimeoutMs);
        } catch (error) {
          cleanup();
          reject(error instanceof Error ? error : new Error('Unknown upload error'));
        }
      };

      reader.onerror = (error) => {
        reject(error instanceof Error ? error : new Error('Failed to read file'));
      };

      reader.readAsDataURL(file);
    });
  }, []);

  return { uploadRknnFile };
};
