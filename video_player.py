import sys
import os
import subprocess
import importlib
import urllib.parse
import json
import xml.etree.ElementTree as ET
import threading

# Importações dos Módulos
from core.utils import log_to_file, load_memory, save_memory, install_pyqt, PLAYLIST_FILE, ADDONS_DIR, PLUGINS_REPO_DIR
from core import kodi_bridge
from core.repository import RepositoryBrowser
from stream_buffer import StreamBuffer
from video_widget import VideoOutputWidget

try:
    import requests
except ImportError:
    requests = None

# Tenta importar PyQt6. Se falhar, usa Tkinter apenas para pedir a instalação.
try:
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QFileDialog, QSlider, 
                                 QLabel, QStyle, QMessageBox, QListWidget, QListWidgetItem,
                                 QDialog, QComboBox, QInputDialog)
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
    # from PyQt6.QtMultimediaWidgets import QVideoWidget # Removido para usar QVideoSink
    from PyQt6.QtCore import Qt, QUrl, QTime, QEvent, QIODevice, pyqtSignal
    from PyQt6.QtGui import QPainter, QImage, QBrush, QColor, QIcon
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QMainWindow = object

if PYQT_AVAILABLE:
    class PyQtKeyboard:
        """Implementação do xbmc.Keyboard usando QInputDialog do PyQt."""
        def __init__(self, default_text='', heading=''):
            self.text = default_text
            self.heading = heading
            self.confirmed = False

        def doModal(self):
            parent = QApplication.activeWindow()
            text, ok = QInputDialog.getText(parent, "Teclado", self.heading, text=self.text)
            if ok:
                self.text = text
                self.confirmed = True
            else:
                self.confirmed = False

        def isConfirmed(self):
            return self.confirmed

        def getText(self):
            return self.text

    # Injeta a implementação do Keyboard no MockXBMC para permitir busca nos plugins
    if hasattr(kodi_bridge, 'MockXBMC'):
        kodi_bridge.MockXBMC.Keyboard = PyQtKeyboard

class VideoPlayer(QMainWindow):
    # Sinal para receber metadados de threads externas (plugins)
    metadata_signal = pyqtSignal(dict)
    # Sinal para atualizar a capa do álbum na thread da GUI
    update_cover_signal = pyqtSignal(QImage)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Player PyQt6 (Áudio + Vídeo + Zoom)")
        self.resize(800, 600)

        # Configura o ícone da janela principal
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Variáveis da Playlist
        self.playlist = []
        self.current_index = -1
        self.playlist_width = 450
        self.current_plugin_path = None # Caminho do plugin carregado
        self.stream_buffer = None # Mantém referência para o buffer atual
        self.plugin_history = [] # Histórico de navegação do plugin
        self.current_plugin_params = "" # Parâmetros atuais do plugin

        # Carrega a memória do player
        self.memory = load_memory()
        
        # Configura o sistema de logs
        self.setup_logging()

        # Registra callback para receber metadados do Kodi Bridge
        self.metadata_signal.connect(self.update_metadata_ui)
        kodi_bridge.register_metadata_callback(self.metadata_signal.emit)

        # Configuração do Player de Mídia
        self.mediaPlayer = QMediaPlayer()
        self.audioOutput = QAudioOutput()
        self.mediaPlayer.setAudioOutput(self.audioOutput)
        
        # Playlist Widget (Overlay)
        self.playlistWidget = QListWidget(self)
        self.playlistWidget.hide()
        self.playlistWidget.setStyleSheet("background-color: rgba(0, 0, 0, 0.8); color: white; border: none; font-size: 14px;")
        self.playlistWidget.itemClicked.connect(self.on_playlist_clicked)

        # --- Interface Gráfica (Layout) ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Widget de Saída de Vídeo (Substitui QVideoWidget e Overlay)
        self.videoOutput = VideoOutputWidget(self.toggle_fullscreen, self.handle_mouse_move, self.play_video)
        layout.addWidget(self.videoOutput)
        self.update_cover_signal.connect(self.videoOutput.set_frame)
        
        # Configura Sink para capturar frames
        self.videoSink = QVideoSink()
        self.mediaPlayer.setVideoSink(self.videoSink)
        self.videoSink.videoFrameChanged.connect(self.handle_frame)

        # Controles
        controls_layout = QHBoxLayout()
        layout.addLayout(controls_layout)

        # Botão Abrir
        self.openBtn = QPushButton("Abrir Vídeo")
        self.openBtn.clicked.connect(self.open_file)
        controls_layout.addWidget(self.openBtn)

        # Botão Carregar Plugin
        self.pluginBtn = QPushButton("Carregar Plugin")
        self.pluginBtn.clicked.connect(self.load_plugin_dialog)
        controls_layout.addWidget(self.pluginBtn)

        # Botão Repositórios
        self.repoBtn = QPushButton("Repositórios")
        self.repoBtn.clicked.connect(self.open_repo_browser)
        controls_layout.addWidget(self.repoBtn)

        # Botão Anterior
        self.prevBtn = QPushButton()
        self.prevBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.prevBtn.clicked.connect(self.play_previous)
        controls_layout.addWidget(self.prevBtn)

        # Botão Play/Pause
        self.playBtn = QPushButton()
        self.playBtn.setEnabled(False)
        self.playBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.playBtn.clicked.connect(self.play_video)
        controls_layout.addWidget(self.playBtn)

        # Botão Stop
        self.stopBtn = QPushButton()
        self.stopBtn.setEnabled(False)
        self.stopBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stopBtn.clicked.connect(self.stop_video)
        controls_layout.addWidget(self.stopBtn)

        # Botão Próximo
        self.nextBtn = QPushButton()
        self.nextBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.nextBtn.clicked.connect(self.play_next)
        controls_layout.addWidget(self.nextBtn)

        # Estilo de alto contraste para os botões de mídia
        media_btn_style = """
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #888;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #fff;
            }
            QPushButton:pressed {
                background-color: #ccc;
            }
            QPushButton:disabled {
                background-color: #e0e0e0;
                border: 1px solid #ccc;
            }
        """
        for btn in [self.prevBtn, self.playBtn, self.stopBtn, self.nextBtn]:
            btn.setStyleSheet(media_btn_style)

        # Slider de Posição (Seekbar)
        self.positionSlider = QSlider(Qt.Orientation.Horizontal)
        self.positionSlider.setRange(0, 0)
        self.positionSlider.sliderMoved.connect(self.set_position)
        controls_layout.addWidget(self.positionSlider)

        # Label de Tempo
        self.timeLabel = QLabel("00:00")
        controls_layout.addWidget(self.timeLabel)

        # Slider de Volume
        self.volumeSlider = QSlider(Qt.Orientation.Horizontal)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setValue(70)
        self.audioOutput.setVolume(0.7) # 0.0 a 1.0
        self.volumeSlider.valueChanged.connect(self.set_volume)
        self.volumeSlider.setFixedWidth(100)
        controls_layout.addWidget(QLabel("Vol:"))
        controls_layout.addWidget(self.volumeSlider)

        # Conexões de Sinais do Player
        self.mediaPlayer.positionChanged.connect(self.position_changed)
        self.mediaPlayer.durationChanged.connect(self.duration_changed)
        self.mediaPlayer.playbackStateChanged.connect(self.media_state_changed)
        self.mediaPlayer.errorOccurred.connect(self.handle_errors)
        self.mediaPlayer.mediaStatusChanged.connect(self.media_status_changed)

        # Tenta restaurar o último plugin usado (opcional)
        if self.memory.get('last_plugin') and os.path.exists(self.memory['last_plugin']):
            log_to_file(f"Restaurando último plugin: {self.memory['last_plugin']}")
            # Descomente a linha abaixo se quiser carregar o plugin automaticamente ao abrir
            # self.current_plugin_path = self.memory['last_plugin']
            # self.run_plugin_action("")

        # Tenta restaurar a última playlist local e vídeo
        last_video = self.memory.get('last_video')
        if last_video and os.path.exists(last_video):
            log_to_file(f"Restaurando último vídeo: {last_video}")
            self.load_video(last_video)

    def setup_logging(self):
        """Redireciona logs do Kodi Bridge para o arquivo."""
        original_log = kodi_bridge.MockXBMC.log
        def file_logger(msg, level=kodi_bridge.MockXBMC.LOGNOTICE):
            original_log(msg, level) # Mantém no console
            log_to_file(f"[KODI] {msg}")
        kodi_bridge.MockXBMC.log = file_logger
        log_to_file("=== Sessão Iniciada ===")

    def update_metadata_ui(self, info):
        """Atualiza a interface com metadados recebidos do plugin (Artista - Música)."""
        title = info.get('title', '')
        artist = info.get('artist', '')
        thumb = info.get('thumb', '') or info.get('icon', '')
        
        display_text = ""
        if artist and title:
            display_text = f"{artist} - {title}"
        elif title:
            display_text = title
            
        if display_text:
            self.setWindowTitle(f"Reproduzindo: {display_text}")

        # Se houver URL de imagem, baixa e exibe
        if thumb and thumb.startswith('http'):
            threading.Thread(target=self.download_and_show_thumb, args=(thumb,), daemon=True).start()

    def download_and_show_thumb(self, url):
        """Baixa a imagem da URL e emite sinal para exibir."""
        if not requests:
            return
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                image = QImage.fromData(response.content)
                if not image.isNull():
                    self.update_cover_signal.emit(image)
        except Exception as e:
            print(f"Erro ao baixar capa: {e}")

    def save_playlist_state(self):
        """Salva a playlist atual para restaurar depois."""
        playlist_data = []
        for i in range(self.playlistWidget.count()):
            item = self.playlistWidget.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            label = item.text()
            import json # Garante importação para uso local se necessário, mas já está no topo
            
            # Remove objetos não serializáveis (como MockListItem) antes de salvar
            clean_data = data
            if isinstance(data, dict):
                clean_data = data.copy()
                if 'listitem' in clean_data:
                    del clean_data['listitem']
            
            # Salva apenas itens de plugin ou caminhos locais simples
            playlist_data.append({'label': label, 'data': clean_data})
        
        try:
            with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(playlist_data, f, indent=4)
        except Exception as e:
            log_to_file(f"Erro ao salvar playlist: {e}")

    def open_file(self):
        start_dir = self.memory.get('last_directory', '')
        
        file_dialog = QFileDialog(self)
        if start_dir and os.path.exists(start_dir):
            file_dialog.setDirectory(start_dir)
        file_dialog.setNameFilters(["Vídeos (*.mp4 *.avi *.mkv *.mov *.mp3)", "Todos (*.*)"])
        if file_dialog.exec():
            files = file_dialog.selectedFiles()
            if files:
                self.load_video(files[0])

    def check_plugin_deps(self):
        """Verifica se requests e bs4 estão instalados e oferece instalação."""
        missing = []
        try:
            import requests
        except ImportError:
            missing.append("requests")
        
        try:
            import bs4
        except ImportError:
            missing.append("beautifulsoup4")

        try:
            import chardet
        except ImportError:
            missing.append("chardet")

        if missing:
            reply = QMessageBox.question(
                self, 
                "Dependências Ausentes",
                f"Para executar plugins de web scraping, as seguintes bibliotecas são necessárias:\n\n{', '.join(missing)}\n\nDeseja instalá-las agora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                    importlib.invalidate_caches()
                    QMessageBox.information(self, "Sucesso", "Bibliotecas instaladas! Agora você pode carregar o plugin.")
                    return True
                except Exception as e:
                    QMessageBox.critical(self, "Erro", f"Falha na instalação: {e}")
                    return False
            return False
        return True

    def open_repo_browser(self):
        if not self.check_plugin_deps():
            return
        
        dialog = RepositoryBrowser(self)
        dialog.exec()

    def get_installed_plugins(self):
        """Escaneia pastas de addons e plugins locais."""
        plugins = []
        # Pastas para escanear: Addons instalados e Plugins de desenvolvimento
        paths_to_scan = [
            (ADDONS_DIR, ""),
            (PLUGINS_REPO_DIR, " [DEV]")
        ]
        
        for base_path, suffix in paths_to_scan:
            if not os.path.exists(base_path):
                continue
                
            for item_name in os.listdir(base_path):
                plugin_path = os.path.join(base_path, item_name)
                if os.path.isdir(plugin_path):
                    entry_point = None
                    name = item_name
                    
                    # 1. Tenta ler addon.xml para achar o entry point correto e o nome
                    addon_xml = os.path.join(plugin_path, "addon.xml")
                    if os.path.exists(addon_xml):
                        try:
                            # Lê o arquivo com tratamento de erro de encoding
                            with open(addon_xml, 'r', encoding='utf-8', errors='ignore') as f:
                                xml_content = f.read()
                            root = ET.fromstring(xml_content)
                            name = root.get("name", item_name)
                            
                            # Procura a extensão que define o script principal
                            for extension in root.findall('extension'):
                                point = extension.get('point')
                                if point in ['xbmc.python.pluginsource', 'xbmc.python.script']:
                                    library = extension.get('library')
                                    if library:
                                        candidate = os.path.normpath(os.path.join(plugin_path, library))
                                        if os.path.exists(candidate):
                                            entry_point = candidate
                                            break
                        except Exception as e:
                            print(f"Falha ao ler addon.xml de {item_name}: {e}")

                    # 2. Fallback: Procura ponto de entrada comum na raiz se não achou no xml
                    if not entry_point:
                        for candidate in ["main.py", "default.py", "service.py", "addon.py"]:
                            if os.path.exists(os.path.join(plugin_path, candidate)):
                                entry_point = os.path.join(plugin_path, candidate)
                                break
                    
                    if entry_point:
                        
                        plugins.append({
                            "label": f"{name} ({item_name}){suffix}",
                            "path": entry_point
                        })
        return plugins

    def load_plugin_dialog(self):
        if not self.check_plugin_deps():
            return

        plugins = self.get_installed_plugins()
        
        # Prepara lista para o diálogo
        items = [p['label'] for p in plugins]
        items.append("📂 Abrir arquivo manualmente...")

        item, ok = QInputDialog.getItem(self, "Carregar Plugin", "Selecione o plugin:", items, 0, False)
        
        if ok and item:
            if item == "📂 Abrir arquivo manualmente...":
                self.open_file_plugin_dialog()
            else:
                for p in plugins:
                    if p['label'] == item:
                        self.run_plugin_from_path(p['path'])
                        break

    def open_file_plugin_dialog(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilters(["Python Script (*.py)", "Todos (*.*)"])
        if file_dialog.exec():
            files = file_dialog.selectedFiles()
            if files:
                self.run_plugin_from_path(files[0])

    def run_plugin_from_path(self, path):
        self.current_plugin_path = path
        self.plugin_history = [] # Reseta histórico ao carregar novo plugin
        self.current_plugin_params = ""
        
        # Atualiza memória
        self.memory['last_plugin'] = self.current_plugin_path
        if self.current_plugin_path not in self.memory['recent_plugins']:
            self.memory['recent_plugins'].append(self.current_plugin_path)
        save_memory(self.memory)
        
        self.run_plugin_action("") # Roda a raiz do plugin

    def run_plugin_action(self, url, is_back=False):
        if not self.current_plugin_path:
            return

        # Executa o plugin via ponte
        data = kodi_bridge.run_plugin(self.current_plugin_path, url)

        # Se o plugin retornou uma URL resolvida (vídeo direto)
        if data["resolved_url"]:
            # Verifica se há DRM
            if data.get("drm_info"):
                drm = data["drm_info"]
                log_to_file(f"DRM Widevine Detectado: {drm}")
                QMessageBox.warning(self, "DRM Protegido", f"Este vídeo requer licença Widevine.\nChave: {drm['key'][:50]}...\n\nO player interno (QMediaPlayer) não suporta descriptografia DRM.\nA reprodução falhará ou ficará preta.")

            self.load_video(data["resolved_url"])
            return

        # Se o plugin retornou uma lista de itens (pastas ou vídeos)
        if data["items"]:
            # Gerencia histórico de navegação
            if not is_back and url != self.current_plugin_params:
                self.plugin_history.append(self.current_plugin_params)
            
            self.current_plugin_params = url

            self.playlist.clear()
            self.playlistWidget.clear()
            
            # Adiciona botão de voltar se houver histórico
            if self.plugin_history:
                back_item = QListWidgetItem(".. (Voltar)")
                back_item.setData(Qt.ItemDataRole.UserRole, {'is_back': True})
                back_item.setForeground(QBrush(QColor("yellow")))
                self.playlistWidget.addItem(back_item)
            
            for item in data["items"]:
                # Adiciona à lista visual
                list_item = QListWidgetItem(item['label'])
                # Armazena os dados do plugin (url, isFolder) dentro do item visual
                # Usamos UserRole para guardar dados customizados
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                self.playlistWidget.addItem(list_item)
            
            # Mostra a playlist se estiver escondida
            if self.playlistWidget.isHidden():
                self.playlistWidget.setGeometry(self.width() - self.playlist_width, 0, self.playlist_width, self.height())
                self.playlistWidget.show()
                self.playlistWidget.raise_()
                self.playlistWidget.setFocus()

    def init_playlist(self, current_file):
        self.playlist.clear()
        self.playlistWidget.clear()
        directory = os.path.dirname(current_file)
        extensions = ('.mp4', '.avi', '.mkv', '.mov', '.mp3', '.webm', '.wav', '.flv')
        
        try:
            # Lista arquivos da pasta, normaliza caminhos e ordena alfabeticamente
            files = sorted([
                os.path.normpath(os.path.join(directory, f))
                for f in os.listdir(directory)
                if f.lower().endswith(extensions)
            ])
            
            self.playlist = files
            for f in files:
                self.playlistWidget.addItem(os.path.basename(f))

            target = os.path.normpath(current_file)
            
            if target in self.playlist:
                self.current_index = self.playlist.index(target)
            else:
                self.playlist = [target]
                self.current_index = 0
            
            self.playlistWidget.setCurrentRow(self.current_index)
            
            # Salva diretório na memória
            self.memory['last_directory'] = directory
            save_memory(self.memory)
        except Exception as e:
            print(f"Erro ao criar playlist: {e}")
            self.playlist = [current_file]
            self.current_index = 0
            self.playlistWidget.addItem(os.path.basename(current_file))
            self.playlistWidget.setCurrentRow(0)

    def load_video(self, file_path):
        # Reseta o buffer anterior se houver
        if self.stream_buffer:
            self.stream_buffer.close()
            self.stream_buffer = None

        # Verifica se a URL tem headers do Kodi (separados por |)
        if "|" in file_path:
            url_part, headers_part = file_path.split("|", 1)
            
            # HLS (m3u8) não funciona bem com StreamBuffer (que é para arquivo único).
            # O FFmpeg/Qt lida nativamente com HLS, então passamos a URL direta.
            if '.m3u8' in url_part:
                self.mediaPlayer.setSource(QUrl(url_part))
                log_to_file(f"Streaming HLS direto (sem buffer): {url_part}")
            else:
                headers = {}
                # Parse dos headers (formato: User-Agent=X&Referer=Y)
                for param in headers_part.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        headers[urllib.parse.unquote(key)] = urllib.parse.unquote(value)
                
                # Usa o StreamBuffer para lidar com a requisição HTTP
                self.stream_buffer = StreamBuffer(url_part, headers)
                if self.stream_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                    self.mediaPlayer.setSourceDevice(self.stream_buffer, QUrl(url_part))
                    log_to_file(f"Streaming iniciado: {url_part}")
                else:
                    print("Falha ao abrir stream com headers")
                    return
        elif file_path.startswith("http://") or file_path.startswith("https://"):
            # URL da web: não podemos criar uma playlist a partir de um diretório.
            # Limpa a playlist interna para evitar tocar o próximo item de uma playlist anterior.
            self.playlist.clear()
            self.current_index = -1
            self.mediaPlayer.setSource(QUrl(file_path))
        else:
            # Arquivo local
            # Popula a playlist e a UI com os arquivos da mesma pasta.
            self.init_playlist(file_path)
            self.mediaPlayer.setSource(QUrl.fromLocalFile(file_path))
            
            # Salva último vídeo local na memória
            self.memory['last_video'] = file_path
            save_memory(self.memory)
            
        self.playBtn.setEnabled(True)
        self.stopBtn.setEnabled(True)
        self.setWindowTitle(f"Reproduzindo: {os.path.basename(file_path.split('|')[0])}")
        self.mediaPlayer.play()

    def play_next(self):
        if self.playlist and self.current_index < len(self.playlist) - 1:
            self.current_index += 1
            self.load_video(self.playlist[self.current_index])
            self.playlistWidget.setCurrentRow(self.current_index)

    def play_previous(self):
        if self.playlist and self.current_index > 0:
            self.current_index -= 1
            self.load_video(self.playlist[self.current_index])
            self.playlistWidget.setCurrentRow(self.current_index)

    def stop_video(self):
        self.mediaPlayer.stop()
        self.videoOutput.set_frame(None)
        
        # Fecha o buffer de stream para parar o download de dados imediatamente
        if self.stream_buffer:
            self.stream_buffer.close()
            self.stream_buffer = None
            
        # Notifica o bridge que o player parou (para plugins que monitoram isPlaying)
        kodi_bridge.MockXBMC.Player().stop()
        self.setWindowTitle("Player PyQt6 (Áudio + Vídeo + Zoom)")

    def on_playlist_clicked(self, item):
        row = self.playlistWidget.row(item)
        
        # Verifica se é um item de plugin (tem dados customizados)
        plugin_data = item.data(Qt.ItemDataRole.UserRole)
        
        if plugin_data:
            # Verifica se é botão de voltar
            if plugin_data.get('is_back'):
                if self.plugin_history:
                    prev_params = self.plugin_history.pop()
                    self.run_plugin_action(prev_params, is_back=True)
                return

            # Se for plugin, executa a ação (navegar ou tocar)
            # A URL do plugin já vem formatada (ex: script.py?action=...)
            url = plugin_data['url']
            self.run_plugin_action(url)
        elif row >= 0 and row < len(self.playlist):
            # Comportamento normal de arquivo local
            self.current_index = row
            self.load_video(self.playlist[row])

    def play_video(self):
        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.mediaPlayer.pause()
        else:
            self.mediaPlayer.play()

    def media_state_changed(self, state):
        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.playBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        else:
            self.playBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_next()

    def position_changed(self, position):
        self.positionSlider.setValue(position)
        # Atualiza label de tempo
        m, s = divmod(position // 1000, 60)
        self.timeLabel.setText(f"{m:02d}:{s:02d}")

    def duration_changed(self, duration):
        self.positionSlider.setRange(0, duration)

    def set_position(self, position):
        self.mediaPlayer.setPosition(position)

    def set_volume(self, volume):
        self.audioOutput.setVolume(volume / 100)

    def handle_errors(self):
        self.playBtn.setEnabled(False)
        self.stopBtn.setEnabled(False)
        err_msg = self.mediaPlayer.errorString()
        print(f"Erro: {err_msg}")
        log_to_file(f"Erro no Player: {err_msg}")

    def handle_frame(self, frame):
        if frame.isValid():
            self.videoOutput.set_frame(frame.toImage())

    def handle_mouse_move(self, event):
        # Exibe a playlist se o mouse estiver a 50px da borda direita
        w = self.videoOutput.width()
        x = event.pos().x()
        
        if x > w - 50:
            if self.playlistWidget.isHidden():
                self.playlistWidget.setGeometry(self.width() - self.playlist_width, 0, self.playlist_width, self.height())
                self.playlistWidget.show()
                self.playlistWidget.raise_()
        elif x < w - self.playlist_width:
            if not self.playlistWidget.isHidden():
                self.playlistWidget.hide()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        if not self.playlistWidget.isHidden():
            self.playlistWidget.setGeometry(self.width() - self.playlist_width, 0, self.playlist_width, self.height())
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.play_video()
        elif event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
        elif event.key() == Qt.Key.Key_Right:
            # Avança 5 segundos
            self.mediaPlayer.setPosition(self.mediaPlayer.position() + 5000)
        elif event.key() == Qt.Key.Key_Left:
            # Volta 5 segundos
            self.mediaPlayer.setPosition(self.mediaPlayer.position() - 5000)
        super().keyPressEvent(event)

    def closeEvent(self, event):
        save_memory(self.memory)
        self.save_playlist_state()
        log_to_file("=== Sessão Finalizada ===\n")
        super().closeEvent(event)

if __name__ == "__main__":
    if not PYQT_AVAILABLE:
        install_pyqt()
    else:
        app = QApplication(sys.argv)
        player = VideoPlayer()
        player.show()
        sys.exit(app.exec())
