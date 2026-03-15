import sys
import os
import subprocess
import importlib
import urllib.parse
import json
import xml.etree.ElementTree as ET
import threading

# Importações dos Módulos
from core.utils import log_to_file, load_memory, save_memory, install_pyqt, PLAYLIST_FILE, ADDONS_DIR, PLUGINS_REPO_DIR, remove_kodi_formatting
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
    from PyQt6.QtCore import Qt, QUrl, QTime, QEvent, QIODevice, pyqtSignal, QThread, QObject
    from PyQt6.QtGui import QPainter, QImage, QBrush, QColor, QIcon
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QMainWindow = object

if PYQT_AVAILABLE:
    class PluginWorker(QObject):
        finished = pyqtSignal(dict)

        def __init__(self, plugin_path, url, parent=None):
            super().__init__(parent)
            self.plugin_path = plugin_path
            self.url = url

        def run(self):
            """Executa o plugin em uma separada thread."""
            data = kodi_bridge.run_plugin(self.plugin_path, self.url)
            self.finished.emit(data)

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
    # Sinal para notificações da thread do plugin para a thread da GUI
    notification_signal = pyqtSignal(str, str)
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
        self.current_media_info = {} # Metadados da mídia atual
        self.thread = None
        self.worker = None

        # Carrega a memória do player
        self.memory = load_memory()
        
        # Configura o sistema de logs
        self.setup_logging()

        # Registra callback para receber metadados do Kodi Bridge
        self.metadata_signal.connect(self.update_metadata_ui)
        kodi_bridge.register_metadata_callback(self.metadata_signal.emit)

        # Registra callback para notificações
        self.notification_signal.connect(self.show_notification)
        kodi_bridge.register_notification_callback(self.notification_signal.emit)

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

    def show_default_audio_ui(self):
        """Cria e exibe uma imagem padrão para quando estiver tocando áudio sem capa."""
        # Cria uma imagem preta
        image = QImage(800, 600, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.black)

        painter = QPainter(image)
        
        # 1. Ícone de música (usando um caractere unicode grande)
        font_icon = painter.font()
        font_icon.setPointSize(150)
        painter.setFont(font_icon)
        painter.setPen(QColor("#333")) # Cinza escuro
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "🎵")

        # 2. Texto "Reproduzindo Áudio"
        font_text = painter.font()
        font_text.setPointSize(24)
        painter.setFont(font_text)
        painter.setPen(QColor("#ccc")) # Cinza claro
        # Desenha o texto abaixo do centro
        text_rect = image.rect().adjusted(0, 250, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Reproduzindo Áudio")

        # 3. Metadata (se disponível, vindo de self.current_media_info)
        title = self.current_media_info.get('title', '')
        artist = self.current_media_info.get('artist', '')
        display_text = f"{remove_kodi_formatting(artist)} - {remove_kodi_formatting(title)}" if artist and title else remove_kodi_formatting(title)
        
        if display_text:
            font_meta = painter.font()
            font_meta.setPointSize(16)
            painter.setFont(font_meta)
            painter.setPen(QColor("white"))
            meta_rect = image.rect().adjusted(50, 310, -50, 0) # Adiciona margens
            painter.drawText(meta_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, display_text)

        painter.end()
        self.update_cover_signal.emit(image)

    def show_notification(self, heading, message):
        """Exibe um diálogo de informação (modal)."""
        QMessageBox.information(self, heading, message)

    def update_metadata_ui(self, info):
        """Atualiza a interface com metadados recebidos do plugin (Artista - Música)."""
        title = info.get('title', '')
        artist = info.get('artist', '')
        thumb = info.get('thumb', '') or info.get('icon', '')
        
        display_text = ""
        if artist and title:
            display_text = f"{remove_kodi_formatting(artist)} - {remove_kodi_formatting(title)}"
        elif title:
            display_text = remove_kodi_formatting(title)
            
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
                            name = remove_kodi_formatting(root.get("name", item_name))
                            
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

        # Salva o estado atual da playlist para restaurar se for apenas um vídeo (não navegação)
        # Evita salvar o item de "Carregando..." se for um redirecionamento interno
        first_item = self.playlistWidget.item(0)
        is_loading = first_item and first_item.text() == "Carregando, aguarde..."
        
        if not is_loading:
            self.temp_playlist_backup = []
            for i in range(self.playlistWidget.count()):
                item = self.playlistWidget.item(i)
                self.temp_playlist_backup.append({
                    'text': item.text(),
                    'data': item.data(Qt.ItemDataRole.UserRole),
                    'foreground': item.foreground()
                })

        # --- UI Feedback: Mostra estado de carregamento ---
        self.playlistWidget.clear()
        loading_item = QListWidgetItem("Carregando, aguarde...")
        loading_item.setFlags(Qt.ItemFlag.NoItemFlags) # Torna o item não selecionável
        self.playlistWidget.addItem(loading_item)
        if self.playlistWidget.isHidden():
            self.playlistWidget.setGeometry(self.width() - self.playlist_width, 0, self.playlist_width, self.height())
            self.playlistWidget.show()
            self.playlistWidget.raise_()
        
        # --- Configuração da Thread ---
        self.thread = QThread()
        self.worker = PluginWorker(self.current_plugin_path, url)
        self.worker.moveToThread(self.thread)

        # Conecta sinais e slots
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_plugin_result)
        # Limpeza
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.clear_thread_references)

        # --- Gerenciamento de Estado (antes de iniciar a thread) ---
        if not is_back and url != self.current_plugin_params:
            self.plugin_history.append(self.current_plugin_params)
        self.current_plugin_params = url

        # Inicia a thread
        self.thread.start()

    def clear_thread_references(self):
        """Nulifica as referências à thread e ao worker para evitar acesso a objetos deletados."""
        self.thread = None
        self.worker = None

    def on_plugin_result(self, data):
        """Lida com o resultado do worker do plugin na thread principal."""
        # Se o plugin retornou uma URL resolvida (vídeo direto)
        if data.get("resolved_url"):
            r_url = data["resolved_url"]
            
            if r_url.startswith("plugin://") and r_url != self.current_plugin_params:
                self.run_plugin_action(r_url)
                return
                
            if r_url.startswith("magnet:"):
                self.run_plugin_action(f"plugin://plugin.video.elementum/play?uri={urllib.parse.quote(r_url)}")
                return

            if data.get("drm_info"):
                drm = data["drm_info"]
                log_to_file(f"DRM Widevine Detectado: {drm}")
                QMessageBox.warning(self, "DRM Protegido", f"Este vídeo requer licença Widevine.\nChave: {drm['key'][:50]}...\n\nO player interno (QMediaPlayer) não suporta descriptografia DRM.\nA reprodução falhará ou ficará preta.")

            # Restaura a playlist anterior, pois não houve mudança de diretório (apenas play)
            self.playlistWidget.clear()
            if hasattr(self, 'temp_playlist_backup') and self.temp_playlist_backup:
                for item_data in self.temp_playlist_backup:
                    item = QListWidgetItem(item_data['text'])
                    item.setData(Qt.ItemDataRole.UserRole, item_data['data'])
                    if item_data['foreground'] != QBrush():
                        item.setForeground(item_data['foreground'])
                    self.playlistWidget.addItem(item)

            # Passa a informação de mídia para o load_video
            self.load_video(data["resolved_url"], data.get("media_info"))
            return

        # Se o plugin retornou uma lista de itens (pastas ou vídeos)
        if data.get("items") is not None:
            self.playlist.clear()
            self.playlistWidget.clear()
            
            if self.plugin_history:
                back_item = QListWidgetItem(".. (Voltar)")
                back_item.setData(Qt.ItemDataRole.UserRole, {'is_back': True})
                back_item.setForeground(QBrush(QColor("yellow")))
                self.playlistWidget.addItem(back_item)
            
            items = data["items"]
            if not items and data.get("error"):
                 error_item = QListWidgetItem(f"Erro: {data['error']}")
                 error_item.setForeground(QBrush(QColor("red")))
                 self.playlistWidget.addItem(error_item)

            for item in items:
                clean_label = remove_kodi_formatting(item['label'])
                list_item = QListWidgetItem(clean_label)
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                self.playlistWidget.addItem(list_item)
        elif data.get("error"):
            self.playlistWidget.clear()
            error_item = QListWidgetItem(f"Erro ao carregar: {data['error']}")
            error_item.setForeground(QBrush(QColor("red")))
            self.playlistWidget.addItem(error_item)

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

    def load_video(self, file_path, media_info=None):
        self.current_media_info = media_info or {}
        
        # Limpa o frame anterior para evitar mostrar a capa do item anterior
        self.videoOutput.set_frame(None)

        # Determina o tipo de mídia para a UI
        media_type = self.current_media_info.get('type')
        if not media_type:
            # Tenta adivinhar pelo nome do arquivo
            if any(file_path.lower().endswith(ext) for ext in ['.mp3', '.wav', '.flac', '.m4a', '.ogg']):
                media_type = 'music'
            else:
                media_type = 'video'
        
        # Se for música, prepara a UI de áudio
        if media_type == 'music':
            icon_url = self.current_media_info.get('icon')
            # Se o plugin não deu um título, usa o nome do arquivo
            if not self.current_media_info.get('title'):
                 self.current_media_info['title'] = os.path.basename(file_path.split('|')[0])

            if icon_url:
                if os.path.exists(icon_url):
                    image = QImage(icon_url)
                    if not image.isNull():
                        self.update_cover_signal.emit(image)
                    else:
                        self.show_default_audio_ui() # Mostra UI padrão se o arquivo de imagem local for inválido
                elif icon_url.startswith('http'):
                    # Mostra a UI padrão imediatamente, e a capa será atualizada quando o download terminar
                    self.show_default_audio_ui()
                    threading.Thread(target=self.download_and_show_thumb, args=(icon_url,), daemon=True).start()
                else:
                    self.show_default_audio_ui()
            else:
                self.show_default_audio_ui()

        """Carrega um vídeo/stream, decidindo se usa o player nativo ou o buffer com requests."""
        if self.stream_buffer:
            self.stream_buffer.close()
            self.stream_buffer = None

        if file_path.startswith("http"):
            url_part = file_path
            headers = {}
            if "|" in file_path:
                url_part, headers_part = file_path.split("|", 1)
                for param in headers_part.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        headers[urllib.parse.unquote(key)] = urllib.parse.unquote(value)
            is_hls = '.m3u8' in url_part
            is_simple_http = url_part.startswith("http://") and not headers
            if is_hls or is_simple_http:
                self.mediaPlayer.setSource(QUrl(url_part))
                log_to_file(f"Streaming nativo (sem buffer): {url_part}")
            else:
                self.stream_buffer = StreamBuffer(url_part, headers)
                if self.stream_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                    self.mediaPlayer.setSourceDevice(self.stream_buffer, QUrl(url_part))
                    log_to_file(f"Streaming via Buffer (requests): {url_part}")
                else:
                    self.handle_errors()
                    return
        else:
            self.init_playlist(file_path)
            self.mediaPlayer.setSource(QUrl.fromLocalFile(file_path))
            self.memory['last_video'] = file_path
            save_memory(self.memory)

        self.playBtn.setEnabled(True)
        self.stopBtn.setEnabled(True)
        title = self.current_media_info.get('title', os.path.basename(file_path.split('|')[0]))
        artist = self.current_media_info.get('artist', '')
        display_title = f"{remove_kodi_formatting(artist)} - {remove_kodi_formatting(title)}" if artist and title else remove_kodi_formatting(title)
        self.setWindowTitle(f"Reproduzindo: {display_title}")
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
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            # O worker será deletado pelo sinal 'finished' conectado. Chamar aqui é redundante.

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
