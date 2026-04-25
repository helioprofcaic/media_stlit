try:
    import requests
except ImportError:
    requests = None
from PyQt6.QtCore import QIODevice, pyqtSignal
from core.utils import log_to_file, load_memory
import threading
import time
from collections import deque

class StreamBuffer(QIODevice):
    """
    Um dispositivo de I/O para o QMediaPlayer que faz streaming de fontes HTTP
    usando a biblioteca `requests`.

    Propósito:
    O QMediaPlayer nativo não suporta o envio de headers HTTP customizados (ex: User-Agent,
    Referer), o que é necessário para muitos streams de vídeo protegidos. Esta classe
    atua como um intermediário:
    1. Usa `requests` para baixar o conteúdo de uma URL com os headers necessários.
    2. O download é feito em uma thread separada para não bloquear a GUI.
    3. Os dados são armazenados em um buffer interno (deque).
    4. O QMediaPlayer lê deste dispositivo como se fosse um arquivo local.
    5. Suporta seeking (busca) para streams que não são ao vivo, usando HTTP Range Requests.
    """
    metadata_changed = pyqtSignal(dict)

    def __init__(self, url, headers, parent=None):
        super().__init__(parent)
        self.url = url
        self.headers = headers
        self._data_size = 0
        self._current_response = None
        self._session = None
        
        # --- Variáveis de Controle do Buffer e Thread ---
        self._buffer = deque()
        self._buffer_size = 0
        
        # Carrega configurações de cache (Kodi style)
        mem = load_memory()
        cache_config = mem.get('cache_config', {})
        self._max_buffer_size = cache_config.get('buffer_size_mb', 128) * 1024 * 1024
        self._read_factor = cache_config.get('read_factor', 4)
        self._chunk_size = cache_config.get('chunk_size_kb', 64) * 1024
        
        log_msg = f"StreamBuffer: Cache Config -> Buffer: {self._max_buffer_size // (1024*1024)}MB, Factor: {self._read_factor}x, Chunk: {self._chunk_size // 1024}KB"
        print(log_msg)
        log_to_file(log_msg)
        
        self._download_thread = None
        self._stop_flag = False  # Sinaliza para a thread de download parar
        self._cond = threading.Condition()  # Sincroniza acesso ao buffer entre as threads
        self._eof = False  # End of file
        self._error = None # Armazena exceções da thread de download
        self._generation = 0
        self._is_prebuffering = False # Flag para silenciar readyRead no início

        if requests:
            self._session = requests.Session()
            # Configura retries e pool para melhor estabilidade e performance
            adapter = requests.adapters.HTTPAdapter(max_retries=3, pool_connections=10, pool_maxsize=10)
            self._session.mount('http://', adapter)
            self._session.mount('https://', adapter)

    def open(self, mode):
        """
        Abre o dispositivo para leitura. Inicia a conexão e o processo de buffering.
        Esta função bloqueia até que o primeiro pedaço de dados esteja disponível
        ou um erro ocorra, para que o QMediaPlayer possa detectar o formato da mídia.
        """
        if mode != QIODevice.OpenModeFlag.ReadOnly:
            return False
        if not requests or not self._session:
            return False
        try:
            # Heurística para detectar live streams e pular a detecção de tamanho
            # Kaza FM usa /Live, outros usam /live ou extensões de streaming
            url_lower = self.url.lower()
            is_live_stream = url_lower.endswith(('.flv', '.ts')) or '/live' in url_lower or 'tsdownloader' in url_lower

            if not is_live_stream:
                # 1. Tenta obter o tamanho via HEAD
                try:
                    head_resp = self._session.head(self.url, headers=self.headers, allow_redirects=True, timeout=15)
                    
                    # Verifica se é servidor de rádio (Icecast/Shoutcast)
                    server_header = head_resp.headers.get('Server', '').lower()
                    if 'icecast' in server_header or 'shoutcast' in server_header:
                        is_live_stream = True

                    if not is_live_stream and 'Content-Length' in head_resp.headers:
                        size = int(head_resp.headers['Content-Length'])
                        # 1073741823 é 0x3FFFFFFF (1GB-1), usado por servidores antigos como "tamanho desconhecido/infinito"
                        # Se encontrar esse valor ou algo absurdo (>100GB), trata como live stream
                        if size == 1073741823 or size > 100 * 1024 * 1024 * 1024:
                            is_live_stream = True
                        else:
                            self._data_size = size
                except Exception as e:
                    print(f"HEAD falhou: {e}")
                    log_to_file(f"StreamBuffer HEAD falhou: {e}")

                # 2. Se falhou e não é live, tenta GET com Range 0-0 para obter Content-Range
                if not is_live_stream and self._data_size == 0:
                    try:
                        headers_range = self.headers.copy()
                        headers_range['Range'] = 'bytes=0-0'
                        range_resp = self._session.get(self.url, headers=headers_range, timeout=15)
                        if range_resp.status_code == 206:
                            content_range = range_resp.headers.get('Content-Range', '')
                            if '/' in content_range:
                                self._data_size = int(content_range.split('/')[-1])
                    except Exception as e:
                        print(f"Range check falhou: {e}")
                        log_to_file(f"StreamBuffer Range check falhou: {e}")
            
            if is_live_stream:
                self._data_size = 0 # Live streams são sequenciais e não têm tamanho definido
                log_to_file(f"StreamBuffer: Live stream detectado ({self.url}), pulando detecção de tamanho.")
            
            print(f"StreamBuffer: Tamanho detectado: {self._data_size}")
            log_to_file(f"StreamBuffer: Tamanho detectado: {self._data_size}")

            # Inicia o stream do começo
            self._start_stream(0)

            # Bloqueia até que o primeiro pedaço de dados chegue ou um erro ocorra.
            # Isso é crucial para que o QMediaPlayer possa sondar o formato do stream corretamente.
            with self._cond:
                while not self._buffer and not self._error and not self._eof:
                    if not self._cond.wait(timeout=25): # Timeout de 25s (maior que o timeout de conexão de 20s)
                        self._error = Exception("Timeout esperando pelo primeiro chunk de dados")
                        break
            
            if self._error:
                raise self._error

            return super().open(mode)
        except Exception as e:
            print(f"Erro ao abrir stream: {e}")
            log_to_file(f"Erro ao abrir stream: {e}")
            return False

    def _start_stream(self, offset):
        """
        Para o download atual (se houver) e inicia um novo a partir de um 'offset'.
        Usado para o início do stream e para operações de seek.
        """
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
                # The 'raw' object might be None if the connection failed early
                if getattr(self._current_response, 'raw', None):
                    self._current_response.raw.close()
                    self._current_response.close()
            except:
                pass
        if self._download_thread and self._download_thread.is_alive():
            self._download_thread.join(timeout=0.2)
        self._download_thread = None
        self._current_response = None

    def _append_to_buffer(self, data, generation):
        """Helper para adicionar dados ao buffer de forma thread-safe."""
        if not data: return
        with self._cond:
            if self._generation != generation: return
            self._buffer.append(data)
            self._buffer_size += len(data)
            self._cond.notify()
        
        # Só emite readyRead se não estivermos no meio do pre-buffering inicial
        if not self._is_prebuffering:
            self.readyRead.emit()
        
        # Controle de fluxo: pausa se o buffer estiver cheio
        while True:
            with self._cond:
                if self._stop_flag or self._buffer_size < self._max_buffer_size or self._generation != generation:
                    break
            time.sleep(0.1)

    def _download_loop(self, initial_offset, generation):
        """
        Thread de download com lógica de reconexão automática e pré-buffering.
        """
        current_offset = initial_offset
        retry_count = 0
        max_retries = 10
        
        # Pré-buffering mais agressivo: no início (offset 0) usamos mais dados para HD/FHD.
        # Se o read_factor for alto (ex: 10x), usamos ele para aumentar o colchão inicial.
        self._is_prebuffering = True
        
        # Base: 8MB para SD, escala com o read_factor para HD.
        # Se read_factor = 4, temos 32MB. Se read_factor = 20, temos 160MB (limitado a 80% do buffer total)
        base_fill = 8 * 1024 * 1024
        min_initial_fill = base_fill * (self._read_factor // 2) if initial_offset == 0 else 1024 * 1024
        
        # Limita o pre-buffering a no máximo 80% do buffer total
        limit_fill = int(self._max_buffer_size * 0.8)
        min_initial_fill = min(min_initial_fill, limit_fill)

        while retry_count < max_retries:
            if self._stop_flag or self._generation != generation:
                break
                
            try:
                req_headers = self.headers.copy()
                req_headers['Accept-Encoding'] = 'identity'
                if current_offset > 0:
                    req_headers['Range'] = f'bytes={current_offset}-'
                
                log_to_file(f"StreamBuffer: Conectando a {self.url} (Offset: {current_offset}, Tentativa: {retry_count+1})")
                response = self._session.get(self.url, headers=req_headers, stream=True, timeout=20)
                self._current_response = response
                
                log_msg = f"StreamBuffer: Resposta HTTP {response.status_code} | Content-Length: {response.headers.get('Content-Length', 'N/A')} | Range: {response.headers.get('Content-Range', 'N/A')}"
                log_to_file(log_msg)
                print(log_msg)
                
                if response.status_code == 416:
                    log_to_file("StreamBuffer: 416 Range Not Satisfiable. Recomeçando do zero...")
                    current_offset = 0
                    continue

                # Verifica se o servidor aceitou o Range request
                bytes_to_skip = 0
                if current_offset > 0 and response.status_code == 200:
                    log_to_file(f"StreamBuffer: Servidor ignorou Range em {current_offset}. Pulando bytes...")
                    print(f"StreamBuffer: Pulando {current_offset} bytes...")
                    bytes_to_skip = current_offset
                    # Se vamos pular muito, o pre-buffering já está ativo
                elif response.status_code >= 400:
                    if response.status_code in [404, 403, 401]:
                        raise Exception(f"Erro HTTP {response.status_code}")
                    response.raise_for_status()

                # Usamos chunk_size=None para que o requests entregue os dados assim que chegarem do socket.
                # Isso reduz drasticamente a latência na alimentação do buffer para streams ao vivo.
                for chunk in response.iter_content(chunk_size=None):
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
                                print("StreamBuffer: Sincronização de bytes concluída.")

                        self._append_to_buffer(chunk, generation)
                        current_offset += len(chunk)
                        retry_count = 0 
                        
                        if self._is_prebuffering and self._buffer_size >= min_initial_fill:
                            log_to_file(f"StreamBuffer: Pré-buffering concluído ({self._buffer_size} bytes)")
                            self._is_prebuffering = False
                            self.readyRead.emit() # Agora liberamos o player
                
                if not self._stop_flag and self._generation == generation:
                    content_length = int(response.headers.get('Content-Length', -1))
                    
                    # Se temos um tamanho definido e não chegamos lá, é erro.
                    # Se não temos tamanho (live stream), tentamos reconectar a menos que
                    # o erro seja explicitamente um fim de stream (raro em HTTP live).
                    if content_length != -1 and current_offset < content_length:
                         raise Exception("Download incompleto (conexão encerrada)")
                    elif content_length == -1:
                        # Para live streams, o fim do loop iter_content sem erro
                        # geralmente significa que a conexão caiu.
                        raise Exception("Stream de tamanho desconhecido interrompido - tentando reconectar")
                    else:
                        # EOF Legítimo (chegamos ao Content-Length)
                        with self._cond:
                            self._eof = True
                            self._cond.notify_all()
                        break 
                else: break

            except Exception as e:
                if self._stop_flag or self._generation != generation: break
                retry_count += 1
                log_to_file(f"StreamBuffer: Erro na tentativa {retry_count}: {e}")
                time.sleep(3) # Espera maior entre retentativas
                continue

        if retry_count >= max_retries:
            with self._cond:
                if self._generation == generation:
                    self._error = Exception(f"Falha persistente após {max_retries} tentativas.")
                    self._cond.notify_all()
                    self.readyRead.emit()

    def _process_icy_metadata(self, data):
        """Extrai informações como StreamTitle dos metadados ICY."""
        try:
            # Remove bytes nulos de preenchimento e decodifica
            meta_str = data.rstrip(b'\0').decode('utf-8', errors='ignore')
            if meta_str:
                # Formato esperado: StreamTitle='Title';StreamUrl='...';
                info = {}
                parts = meta_str.split(';')
                for part in parts:
                    if '=' in part:
                        key, value = part.split('=', 1)
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        info[key] = value
                if info:
                    self.metadata_changed.emit(info)
        except:
            pass

    def readData(self, maxlen):
        """
        Chamado pelo QMediaPlayer quando ele precisa de mais dados para reproduzir.
        Lê até 'maxlen' bytes do buffer interno e os retorna. Se o buffer estiver
        vazio, ele espera por um curto período até que a thread de download o preencha.
        """
        with self._cond:
            # Espera até ter pelo menos um pouco de dados (ex: 32KB para HD ou chunk_size)
            # Isso evita retornar blocos minúsculos que podem causar stutter no motor do player
            min_read = min(32768, maxlen)
            while self._buffer_size < min_read and not self._eof and not self._error and not self._stop_flag:
                # Aumentamos o timeout de espera para 2.0s para ser mais resiliente a jitter de rede
                if not self._cond.wait(timeout=2.0):
                    if self._buffer_size > 0:
                        break
                    # Se não tem NADA, continuamos no loop ou falhamos se retry_count da thread estiver alto
                    
            if not self._buffer and (self._eof or self._error):
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
        """
        Implementa a funcionalidade de busca. Reinicia o stream de download
        a partir da nova posição 'pos' usando um HTTP Range Request.
        """
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