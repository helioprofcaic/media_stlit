try:
    import requests
except ImportError:
    requests = None
from PyQt6.QtCore import QIODevice
from core.utils import log_to_file
import threading
import time
from collections import deque

class StreamBuffer(QIODevice):
    """Buffer que usa requests para fazer streaming de vídeo com headers personalizados e bufferização assíncrona"""
    def __init__(self, url, headers, parent=None):
        super().__init__(parent)
        self.url = url
        self.headers = headers
        self._data_size = 0
        self._current_response = None
        self._session = None
        
        # Variáveis de controle do buffer
        self._buffer = deque()
        self._buffer_size = 0
        self._max_buffer_size = 32 * 1024 * 1024  # 32MB de buffer
        self._download_thread = None
        self._stop_flag = False
        self._cond = threading.Condition()
        self._eof = False
        self._error = None
        self._generation = 0

        if requests:
            self._session = requests.Session()
            # Configura retries e pool para melhor estabilidade e performance
            adapter = requests.adapters.HTTPAdapter(max_retries=3, pool_connections=10, pool_maxsize=10)
            self._session.mount('http://', adapter)
            self._session.mount('https://', adapter)

    def open(self, mode):
        if mode != QIODevice.OpenModeFlag.ReadOnly:
            return False
        if not requests or not self._session:
            return False
        try:
            # 1. Tenta obter o tamanho via HEAD
            try:
                head_resp = self._session.head(self.url, headers=self.headers, allow_redirects=True, timeout=5)
                if 'Content-Length' in head_resp.headers:
                    self._data_size = int(head_resp.headers['Content-Length'])
            except Exception as e:
                print(f"HEAD falhou: {e}")
                log_to_file(f"StreamBuffer HEAD falhou: {e}")

            # 2. Se falhou, tenta GET com Range 0-0 para obter Content-Range
            if self._data_size == 0:
                try:
                    headers_range = self.headers.copy()
                    headers_range['Range'] = 'bytes=0-0'
                    range_resp = self._session.get(self.url, headers=headers_range, timeout=5)
                    if range_resp.status_code == 206:
                        content_range = range_resp.headers.get('Content-Range', '')
                        if '/' in content_range:
                            self._data_size = int(content_range.split('/')[-1])
                except Exception as e:
                    print(f"Range check falhou: {e}")
                    log_to_file(f"StreamBuffer Range check falhou: {e}")
            
            print(f"StreamBuffer: Tamanho detectado: {self._data_size}")
            log_to_file(f"StreamBuffer: Tamanho detectado: {self._data_size}")

            # Inicia o stream do começo
            self._start_stream(0)
            return super().open(mode)
        except Exception as e:
            print(f"Erro ao abrir stream: {e}")
            log_to_file(f"Erro ao abrir stream: {e}")
            return False

    def _start_stream(self, offset):
        self._stop_download()
        
        with self._cond:
            self._generation += 1
            current_gen = self._generation
            self._buffer.clear()
            self._buffer_size = 0
            self._eof = False
            self._error = None
            self._stop_flag = False

        self._download_thread = threading.Thread(target=self._download_loop, args=(offset, current_gen), daemon=True)
        self._download_thread.start()

    def _stop_download(self):
        with self._cond:
            self._stop_flag = True
            self._cond.notify_all()

        if self._current_response:
            try:
                self._current_response.close() # Força a interrupção do read bloqueante
            except:
                pass
        if self._download_thread and self._download_thread.is_alive():
            self._download_thread.join(timeout=0.2)
        self._download_thread = None
        self._current_response = None

    def _download_loop(self, offset, generation):
        try:
            req_headers = self.headers.copy()
            req_headers['Accept-Encoding'] = 'identity'
            if offset > 0:
                req_headers['Range'] = f'bytes={offset}-'
            
            self._current_response = self._session.get(self.url, headers=req_headers, stream=True, timeout=10)
            
            # Verifica se o servidor aceitou o Range request
            bytes_to_skip = 0
            if offset > 0 and self._current_response.status_code == 200:
                print(f"StreamBuffer: Servidor ignorou Range {offset}. Baixando desde o início (fallback).")
                bytes_to_skip = offset
            else:
                self._current_response.raise_for_status()
            
            # chunk_size definido para evitar flood de sinais readyRead que trava a GUI
            for chunk in self._current_response.iter_content(chunk_size=32 * 1024):
                with self._cond:
                    if self._stop_flag or self._generation != generation:
                        break
                
                if chunk:
                    if bytes_to_skip > 0:
                        if len(chunk) <= bytes_to_skip:
                            bytes_to_skip -= len(chunk)
                            continue
                        else:
                            chunk = chunk[bytes_to_skip:]
                            bytes_to_skip = 0

                    with self._cond:
                        if self._generation != generation:
                            break
                        self._buffer.append(chunk)
                        self._buffer_size += len(chunk)
                        self._cond.notify()
                    
                    # Notifica a thread principal que há dados
                    self.readyRead.emit()

                    # Controle de fluxo: pausa se o buffer estiver cheio
                    while True:
                        with self._cond:
                            if self._stop_flag or self._buffer_size < self._max_buffer_size or self._generation != generation:
                                break
                        time.sleep(0.1)
            
            with self._cond:
                if not self._stop_flag and self._generation == generation:
                    self._eof = True
                    self._cond.notify_all()
                if self._generation == generation:
                    self.readyRead.emit()

        except Exception as e:
            with self._cond:
                if self._generation == generation:
                    print(f"Erro no download (thread): {e}")
                    self._error = e
                    self._cond.notify_all()
                    self.readyRead.emit()

    def readData(self, maxlen):
        with self._cond:
            while not self._buffer and not self._eof and not self._error and not self._stop_flag:
                if not self._cond.wait(timeout=0.5):
                    return b""

            if not self._buffer:
                if self._error:
                    print(f"StreamBuffer readData: Erro detectado: {self._error}")
                return b""
            
            data = b""
            while self._buffer and len(data) < maxlen:
                chunk = self._buffer[0]
                needed = maxlen - len(data)
                
                if len(chunk) <= needed:
                    data += chunk
                    self._buffer.popleft()
                    self._buffer_size -= len(chunk)
                else:
                    data += chunk[:needed]
                    self._buffer[0] = chunk[needed:]
                    self._buffer_size -= needed
            
            return data

    def bytesAvailable(self):
        with self._cond:
            return self._buffer_size + super().bytesAvailable()

    def isSequential(self):
        # Se não temos o tamanho, somos sequenciais (não dá pra fazer seek)
        return self._data_size == 0

    def size(self):
        return self._data_size

    def seek(self, pos):
        if self.isSequential():
            return False
            
        if not super().seek(pos):
            return False
            
        # Reinicia a conexão na nova posição (HTTP Range)
        try:
            self._start_stream(pos)
            return True
        except Exception as e:
            print(f"Erro ao buscar (seek): {e}")
            return False
            
    def close(self):
        self._stop_download()
        if self._session:
            self._session.close()
        super().close()