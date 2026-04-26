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
from core.proxy import ProxyServer
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
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QMediaMetaData
    from PyQt6.QtCore import Qt, QUrl, QTime, QEvent, QIODevice, pyqtSignal, QThread, QObject, QMetaObject, Q_ARG, pyqtSlot
    from PyQt6.QtGui import QPainter, QImage, QBrush, QColor, QIcon, QPixmap
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QMainWindow = object

# Adiciona importações que podem ter faltado
if PYQT_AVAILABLE:
    from PyQt6.QtCore import QTimer
    from modules.qt6_ui_player import VideoPlayerUI

if PYQT_AVAILABLE:
    def get_info_from_listitem(li):
        """Extrai um dicionário de informações de um MockListItem."""
        if not li: return {}
        
        # O objeto 'li' é um MockListItem do kodi_bridge
        info = getattr(li, 'info', {}).copy()
        art = getattr(li, 'art', {}).copy()
        item_type = getattr(li, 'media_type', 'video')
        
        # O título pode estar no label ou no info dict
        title = info.get('title', '')
        if not title and hasattr(li, 'getLabel'):
            title = li.getLabel()

        return {
            "title": title,
            "artist": info.get('artist'),
            "plot": info.get('plot'),
            "icon": art.get('icon') or art.get('thumb'),
            "fanart": art.get('fanart'),
            "type": item_type
        }

    class PluginWorker(QObject):
        finished = pyqtSignal(dict)

        def __init__(self, plugin_path, url, dialog_answers=None, parent=None):
            super().__init__(parent)
            self.plugin_path = plugin_path
            self.url = url
            self.dialog_answers = dialog_answers
        
        def run(self):
            """Executa o plugin em uma thread separada."""
            try:
                # Passa o nome do addon para o kodi_bridge para que as configurações sejam salvas corretamente
                addon_id = os.path.basename(os.path.dirname(self.plugin_path))
                kodi_bridge.set_current_addon_id(addon_id)
                data = kodi_bridge.run_plugin(self.plugin_path, self.url, self.dialog_answers)
            except BaseException as e:
                data = {"error": f"Crash irrecuperável no Plugin: {str(e)}"}
            self.finished.emit(data)

    class InputHelper(QObject):
        """Helper para executar QInputDialog na thread principal."""
        def __init__(self):
            super().__init__()
            self.text = ""
            self.confirmed = False

        @pyqtSlot(str, str, str)
        def show_input(self, title, heading, default_text):
            parent = QApplication.activeWindow()
            text, ok = QInputDialog.getText(parent, title, heading, text=default_text)
            self.text = text
            self.confirmed = ok
            
    _input_helper = None

    class PyQtKeyboard:
        """Implementação do xbmc.Keyboard usando QInputDialog do PyQt."""
        def __init__(self, default_text='', heading=''):
            self.text = default_text
            self.heading = heading
            self.confirmed = False

        def doModal(self):
            global _input_helper
            # Se já estiver na main thread, executa direto
            if QThread.currentThread() == QApplication.instance().thread():
                parent = QApplication.activeWindow()
                text, ok = QInputDialog.getText(parent, "Teclado", self.heading, text=self.text)
                if ok:
                    self.text = text
                    self.confirmed = True
                else:
                    self.confirmed = False
                return

            if _input_helper is None:
                 print("InputHelper não inicializado.")
                 return

            QMetaObject.invokeMethod(_input_helper, "show_input",
                                     Qt.ConnectionType.BlockingQueuedConnection,
                                     Q_ARG(str, "Teclado"),
                                     Q_ARG(str, self.heading),
                                     Q_ARG(str, self.text))
            
            if _input_helper.confirmed:
                self.text = _input_helper.text
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
    # Sinal para atualizar a imagem na sidebar de detalhes
    update_details_image_signal = pyqtSignal(QImage)
    # Sinal para atualizar o fundo de tela
    update_background_signal = pyqtSignal(QPixmap)

    def __init__(self, python_executable=None):
        super().__init__()
        self.setWindowTitle("Player PyQt6 (Áudio + Vídeo + Zoom)")
        self.resize(800, 600)
        self.python_executable = python_executable or sys.executable

        global _input_helper
        if _input_helper is None:
            _input_helper = InputHelper()

        # Inicia o proxy local para HLS
        self.proxy_server = ProxyServer()
        self.proxy_server.start()

        # Configura o ícone da janela principal
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Variáveis da Playlist
        self.playlist = []
        self.current_index = -1
        self.playlist_width = 450
        self.details_width = 350
        self.current_plugin_path = None # Caminho do plugin carregado
        self.stream_buffer = None # Mantém referência para o buffer atual
        self.plugin_history = [] # Histórico de navegação do plugin
        self.current_plugin_params = "" # Parâmetros atuais do plugin
        self.pending_dialog_url = None # Armazena a URL que causou um diálogo
        self.current_media_info = {} # Metadados da mídia atual
        self.station_name = "" # Nome da estação de rádio
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

        # Registra callback para o fundo de tela
        self.update_background_signal.connect(self.set_background_pixmap)
        
        # Registra callback para a imagem de detalhes
        self.update_details_image_signal.connect(self.set_details_image)

        # Configuração do Player de Mídia
        self.mediaPlayer = QMediaPlayer()
        self.audioOutput = QAudioOutput()

        # --- Construção da Interface Gráfica via Módulo Externo ---
        self.ui = VideoPlayerUI()
        self.ui.setup_ui(self)

        # Configuração Adicional de Áudio e Vídeo
        self.mediaPlayer.setAudioOutput(self.audioOutput)
        self.update_cover_signal.connect(self.videoOutput.set_frame)
        
        # Configura Sink para capturar frames
        self.videoSink = QVideoSink()
        self.mediaPlayer.setVideoSink(self.videoSink)
        self.videoSink.videoFrameChanged.connect(self.handle_frame)

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
        for btn in [self.prevBtn, self.playBtn, self.stopBtn, self.nextBtn, self.settingsBtn]:
            btn.setStyleSheet(media_btn_style)

        # Conexões de Sinais da UI
        self.playlistWidget.itemClicked.connect(self.on_playlist_clicked)
        self.playlistWidget.currentItemChanged.connect(self.on_playlist_selection_changed)
        self.openBtn.clicked.connect(self.open_file)
        self.pluginBtn.clicked.connect(self.load_plugin_dialog)
        self.repoBtn.clicked.connect(self.open_repo_browser)
        self.prevBtn.clicked.connect(self.play_previous)
        self.playBtn.clicked.connect(self.play_video)
        self.stopBtn.clicked.connect(self.stop_video)
        self.nextBtn.clicked.connect(self.play_next)
        self.settingsBtn.clicked.connect(self.open_settings_dialog)
        self.positionSlider.sliderMoved.connect(self.set_position)
        self.volumeSlider.valueChanged.connect(self.set_volume)
        
        # Inicializa Volume
        self.audioOutput.setVolume(0.7) # 0.0 a 1.0

        # Conexões de Sinais do Player
        self.mediaPlayer.positionChanged.connect(self.position_changed)
        self.mediaPlayer.durationChanged.connect(self.duration_changed)
        self.mediaPlayer.playbackStateChanged.connect(self.media_state_changed)
        self.mediaPlayer.errorOccurred.connect(self.handle_errors)
        self.mediaPlayer.mediaStatusChanged.connect(self.media_status_changed)
        self.mediaPlayer.metaDataChanged.connect(self.on_meta_data_changed)

        # Tenta restaurar o último plugin usado para uma inicialização mais rápida
        last_plugin_path = self.memory.get('last_plugin')
        if last_plugin_path and os.path.exists(last_plugin_path):
            log_to_file(f"Restaurando último plugin: {last_plugin_path}")
            self.run_plugin_from_path(last_plugin_path)

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

        # 2. Nome da estação
        if self.station_name:
            font_station = painter.font()
            font_station.setPointSize(24)
            painter.setFont(font_station)
            painter.setPen(QColor("#ccc")) # Cinza claro
            station_rect = image.rect().adjusted(0, 250, 0, 0)
            painter.drawText(station_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.station_name)
        else:
            font_text = painter.font()
            font_text.setPointSize(24)
            painter.setFont(font_text)
            painter.setPen(QColor("#ccc")) # Cinza claro
            text_rect = image.rect().adjusted(0, 250, 0, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Reproduzindo Áudio")

        # 3. Metadata da música (se disponível)
        title = self.current_media_info.get('title', '')
        artist = self.current_media_info.get('artist', '')
        
        # Não mostra o nome da estação como título da música se for a mesma coisa
        if title == self.station_name and not artist:
            display_text = ""
        else:
            display_text = f"{remove_kodi_formatting(artist)} - {remove_kodi_formatting(title)}" if artist and title else remove_kodi_formatting(title)
        
        if display_text:
            font_meta = painter.font()
            font_meta.setPointSize(16)
            painter.setFont(font_meta)
            painter.setPen(QColor("white"))
            # Ajusta a posição para ficar abaixo do nome da estação
            meta_rect = image.rect().adjusted(50, 310, -50, 0)
            painter.drawText(meta_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, display_text)

        painter.end()
        self.update_cover_signal.emit(image)

    def show_notification(self, heading, message):
        """Mostra uma notificação na tela principal."""
        clean_heading = remove_kodi_formatting(heading)
        clean_message = remove_kodi_formatting(message)
        self.statusBar().showMessage(f"{clean_heading}: {clean_message}", 5000)

    def on_meta_data_changed(self):
        """Lida com a mudança de metadados do stream (ex: título da música em rádio)."""
        # Em PyQt6, acessamos os metadados diretamente. Se não houver, retorna vazio.
        metadata = self.mediaPlayer.metaData()
        
        if not metadata:
            return

        # Em PyQt6, usamos o método .value() com a chave do enum.
        # O backend (FFmpeg) mapeia o metadata 'StreamTitle' para 'Title'.
        stream_title = metadata.value(QMediaMetaData.Key.Title)
        
        # Verifica se o título mudou
        # Usamos uma chave interna para não reprocessar a mesma string
        if stream_title and stream_title != self.current_media_info.get('_raw_stream_title'):
            self.current_media_info['_raw_stream_title'] = stream_title
            artist = ""
            title = ""
            if ' - ' in stream_title:
                parts = stream_title.split(' - ', 1)
                artist = parts[0].strip()
                title = parts[1].strip()
            else:
                title = stream_title.strip()

            # Atualiza a informação da música
            self.current_media_info['artist'] = artist
            self.current_media_info['title'] = title
            
            # Atualiza o título da janela para mostrar estação e música
            song_display = f"{artist} - {title}" if artist and title else title
            self.setWindowTitle(f"{self.station_name} | {song_display}" if self.station_name else f"Reproduzindo: {song_display}")

            # Se for áudio, redesenha a UI com a nova informação
            if self.current_media_info.get('type') == 'music':
                self.show_default_audio_ui()

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

    @pyqtSlot(QPixmap)
    def set_background_pixmap(self, pixmap):
        """Define o QPixmap no QLabel de fundo, escalando e escurecendo."""
        if not pixmap.isNull():
            # Escala para preencher a janela, cortando o excesso
            scaled_pixmap = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            
            # Cria uma imagem para poder desenhar sobre ela
            image = QImage(scaled_pixmap.size(), QImage.Format.Format_ARGB32_Premultiplied)
            painter = QPainter(image)
            painter.drawPixmap(0, 0, scaled_pixmap)
            
            # Pinta um overlay preto semi-transparente para escurecer
            painter.fillRect(image.rect(), QColor(0, 0, 0, 180)) # 180/255 de opacidade
            painter.end()
            
            self.backgroundLabel.setPixmap(QPixmap.fromImage(image))
        else:
            self.backgroundLabel.clear()
            self.backgroundLabel.setStyleSheet("background-color: #1a1a1a;")

    def update_background(self, url):
        """Baixa uma imagem em uma thread e emite um sinal para atualizar o fundo."""
        if not url or not requests:
            self.update_background_signal.emit(QPixmap()) # Emite pixmap vazio para limpar
            return
        
        try:
            if url.startswith('http'):
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    self.update_background_signal.emit(pixmap)
            elif os.path.exists(url):
                self.update_background_signal.emit(QPixmap(url))
        except Exception as e:
            log_to_file(f"Erro ao baixar fanart de fundo: {e}")

    def set_fanart_background(self, fanart_url):
        """Inicia uma thread para atualizar o fundo com a URL do fanart."""
        # Usa o fanart do addon como fallback se nenhum for fornecido
        if not fanart_url and self.current_plugin_path:
            plugin_dir = os.path.dirname(self.current_plugin_path)
            fallback_fanart = os.path.join(plugin_dir, 'fanart.jpg')
            if os.path.exists(fallback_fanart):
                fanart_url = fallback_fanart
            
        threading.Thread(target=self.update_background, args=(fanart_url,), daemon=True).start()

    def set_details_image(self, image):
        """Define a imagem na sidebar de detalhes, escalando-a corretamente."""
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            # Escala a imagem para caber na largura da sidebar, mantendo a proporção
            scaled_pixmap = pixmap.scaledToWidth(self.details_width - 20, Qt.TransformationMode.SmoothTransformation)
            self.detailsImageLabel.setPixmap(scaled_pixmap)
            self.detailsImageLabel.show()
        else:
            self.detailsImageLabel.hide()
            self.detailsImageLabel.clear()

    def download_details_image(self, url):
        """Baixa a imagem da URL em uma thread e emite sinal para exibir."""
        if not requests: return
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                image = QImage.fromData(response.content)
                self.update_details_image_signal.emit(image)
        except Exception as e:
            log_to_file(f"Erro ao baixar imagem de detalhes: {e}")

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
                self.init_playlist(files[0])
                self.load_video(files[0])

    def check_plugin_deps(self):
        """Verifica se requests, bs4 e cloudscraper estão instalados e oferece instalação."""
        dependencies = {
            "requests": "requests",
            "bs4": "beautifulsoup4",
            "cloudscraper": "cloudscraper",
            "chardet": "chardet"
        }
        missing = []
        
        # Verifica cada dependência
        for import_name, pip_name in dependencies.items():
            if importlib.util.find_spec(import_name) is None:
                try:
                    __import__(import_name)
                except ImportError:
                    missing.append(pip_name)


        if missing:
            reply = QMessageBox.question(
                self, 
                "Dependências Ausentes",
                f"Para executar plugins de web scraping, as seguintes bibliotecas são necessárias:\n\n{', '.join(missing)}\n\nDeseja instalá-las agora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    subprocess.check_call([self.python_executable, "-m", "pip", "install"] + missing)
                    # A instalação foi bem-sucedida. Informa o usuário e fecha o app para que as mudanças tenham efeito.
                    QMessageBox.information(self, "Instalação Concluída", "As dependências foram instaladas com sucesso.\n\nPor favor, reinicie o aplicativo para continuar.")
                    sys.exit(0) # Encerra o programa
                except Exception as e:
                    QMessageBox.critical(self, "Erro", f"Falha na instalação: {e}")
                    return False
            # Se o usuário clicar em "Não", a função retorna False e a ação é cancelada.
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

    def run_plugin_action(self, url, is_back=False, dialog_answers=None):
        if not self.current_plugin_path:
            return

        # Limpa a lista interna de arquivos locais para evitar conflitos de índices
        # Isso impede que o player tente carregar um arquivo local ao clicar no "Voltar" do plugin
        self.playlist = []

        # Salva o estado atual da playlist para restaurar se for apenas um vídeo
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
        self.worker = PluginWorker(self.current_plugin_path, url, dialog_answers)
        self.worker.moveToThread(self.thread)

        # Conecta sinais e slots
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_plugin_result)
        # Limpeza
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: setattr(self, 'thread', None))

        # --- Gerenciamento de Estado (antes de iniciar a thread) ---
        # Adiciona ao histórico apenas se a URL for diferente da atual, para evitar duplicatas
        if not is_back:
            # Pega a última URL do histórico, se houver
            last_url_in_history = self.plugin_history[-1] if self.plugin_history else None
            if url != last_url_in_history:
                self.plugin_history.append(self.current_plugin_params)
        self.current_plugin_params = url # Atualiza o parâmetro atual

        # Inicia a thread
        self.thread.start()

    def on_plugin_result(self, data):
        """Lida com o resultado do worker do plugin na thread principal."""
        # Se o plugin retornou uma URL resolvida (vídeo direto)
        if data.get("error"):
            self.playlistWidget.clear()
            error_item = QListWidgetItem(f"Erro no Plugin: {data['error']}")
            error_item.setForeground(QBrush(QColor("red")))
            self.playlistWidget.addItem(error_item)
            return

        if data.get("resolved_url"):
            r_url = data["resolved_url"]
            
            # Se o plugin retornou outra URL de plugin, executa-a
            if r_url.startswith("plugin://"):
                self.run_plugin_action(r_url)
                return

            if data.get("drm_info"):
                drm = data["drm_info"]
                log_to_file(f"DRM Widevine Detectado: {drm}")
                QMessageBox.warning(self, "DRM Protegido", f"Este vídeo requer licença Widevine.\nChave: {drm['key'][:50]}...\n\nO player interno (QMediaPlayer) não suporta descriptografia DRM.\nA reprodução falhará ou ficará preta.")

            # Passa a informação de mídia para o load_video
            self.load_video(r_url, data.get("media_info"))
            # Esconde a lista de plugins/arquivos para focar no vídeo/áudio
            if not self.playlistWidget.isHidden():
                self.playlistWidget.hide()
            
            # Restaura a playlist anterior (backup) se houver, substituindo o "Carregando..."
            if hasattr(self, 'temp_playlist_backup') and self.temp_playlist_backup:
                self.playlistWidget.clear()
                for item_data in self.temp_playlist_backup:
                    item = QListWidgetItem(item_data['text'])
                    item.setData(Qt.ItemDataRole.UserRole, item_data['data'])
                    item.setForeground(item_data['foreground'])
                    self.playlistWidget.addItem(item)
            elif self.playlistWidget.count() > 0 and self.playlistWidget.item(0).text() == "Carregando, aguarde...":
                self.playlistWidget.clear()
                
            return

        # --- Tratamento de Diálogos ---
        dialog_type = data.get("dialog_type")
        if dialog_type:
            if dialog_type == "select":
                heading = remove_kodi_formatting(data.get("heading", "Selecione uma opção"))
                raw_options = data.get("options", [])
                clean_options = [remove_kodi_formatting(opt) for opt in raw_options]
                
                item, ok = QInputDialog.getItem(self, "Seleção", heading, clean_options, 0, False)
                if ok and item:
                    idx = clean_options.index(item)
                    # Retoma a execução do plugin passando a resposta
                    self.run_plugin_action(self.current_plugin_params, dialog_answers=[idx])
                else:
                    self.run_plugin_action(self.plugin_history.pop(), is_back=True) # Volta para a tela anterior se o usuário cancelar
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
            for item in items:
                clean_label = remove_kodi_formatting(item['label'])
                list_item = QListWidgetItem(clean_label)
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                self.playlistWidget.addItem(list_item)
            
            # Seleciona o primeiro item para mostrar metadados automaticamente (se não for botão de voltar)
            if self.playlistWidget.count() > 0:
                start_idx = 1 if self.plugin_history and self.playlistWidget.count() > 1 else 0
                self.playlistWidget.setCurrentRow(start_idx)

    def init_playlist(self, current_file):
        self.playlist.clear()
        self.playlistWidget.clear()
        
        # Garante caminho absoluto se for arquivo local (evita erros com paths relativos)
        if current_file and not os.path.dirname(current_file) and os.path.exists(current_file):
            current_file = os.path.abspath(current_file)
            
        directory = os.path.dirname(current_file)
        extensions = ('.mp4', '.avi', '.mkv', '.mov', '.mp3', '.webm', '.wav', '.flv', '.strm')
        
        try:
            # Se o diretório não existir (ex: URL não-HTTP ou path vazio), usa modo de item único
            if not directory or not os.path.exists(directory):
                self.playlist = [current_file]
                self.current_index = 0
                self.playlistWidget.addItem(os.path.basename(current_file))
                self.playlistWidget.setCurrentRow(0)
                return

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

    def load_video(self, file_path, media_info=None): # media_info é um dict com 'title', 'plot', 'icon', etc.
        self.current_media_info = media_info or {}
        self.station_name = "" # Reseta o nome da estação
        
        # --- Preenche a sidebar de detalhes ---
        title = remove_kodi_formatting(self.current_media_info.get('title', ''))
        plot = self.current_media_info.get('plot', '') # Pode conter dados estruturados
        icon_url = self.current_media_info.get('icon', '')
        fanart_url = self.current_media_info.get('fanart', '')
        self._parse_and_display_details(title, plot, icon_url, fanart_url)

        # --- Tratamento de arquivos .strm (Links de Texto) ---
        if not file_path.startswith("http") and file_path.lower().endswith(".strm") and os.path.exists(file_path):
            try:
                if not self.current_media_info.get('title'):
                    self.current_media_info['title'] = os.path.splitext(os.path.basename(file_path))[0]
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content:
                    log_to_file(f"Resolvendo .strm: {file_path} -> {content}")
                    if content.startswith("plugin://"):
                        self.run_plugin_action(content)
                        return
                    file_path = content
            except Exception as e:
                log_to_file(f"Erro ao ler .strm: {e}")
        
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
        self.current_media_info['type'] = media_type
        
        # Se for música, prepara a UI de áudio
        if media_type == 'music':
            self.station_name = remove_kodi_formatting(self.current_media_info.get('title', ''))
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
        # Reseta o buffer anterior se houver
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

            # --- Lógica de Seleção de Player (Proxy vs Buffer) ---
            is_hls = any(p in url_part.lower() for p in ['.m3u8', '/m3u8/', 'master.txt', 'index.txt', 'playlist.m3u8', '.ts', '.m4s', '.mpd', '/hls/'])
            
            # Usa o proxy para streams HLS que precisam de headers ou que são de servidores locais (ex: Elementum)
            should_proxy_hls = is_hls and (bool(headers) or '127.0.0.1' in url_part or '192.168.' in url_part or 'localhost' in url_part)

            if should_proxy_hls:
                final_url = self.proxy_server.get_proxy_url(url_part, headers)
                self.mediaPlayer.setSource(QUrl(final_url))
                log_to_file(f"Streaming HLS via Proxy Interno: {final_url}")
            else:
                # Para todos os outros casos (links diretos, MP4 com headers, etc.), usa o StreamBuffer
                self.stream_buffer = StreamBuffer(url_part, headers)
                if self.stream_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                    self.stream_buffer.metadata_changed.connect(self.update_stream_metadata)
                    self.mediaPlayer.setSourceDevice(self.stream_buffer, QUrl())
                    log_to_file(f"Streaming via Buffer (requests): {url_part} | Headers: {headers}")
                else:
                    self.handle_errors()
                    return
        else:
            if os.path.exists(file_path):
                self.init_playlist(file_path)
                self.mediaPlayer.setSource(QUrl.fromLocalFile(file_path))
                self.memory['last_video'] = file_path
                save_memory(self.memory)
            else:
                QMessageBox.critical(self, "Erro", f"Arquivo não encontrado:\n{file_path}")
                self.handle_errors()
                return
            
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

    def update_stream_metadata(self, metadata):
        """Atualiza a UI com metadados vindos do StreamBuffer (Rádios ICY)."""
        stream_title = metadata.get('StreamTitle')
        if stream_title:
            # Verifica se o título realmente mudou para evitar processamento desnecessário
            if stream_title == self.current_media_info.get('_raw_stream_title'):
                return

            self.current_media_info['_raw_stream_title'] = stream_title
            
            # Separa Artista - Música se possível
            artist = ""
            title = stream_title.strip()
            if ' - ' in stream_title:
                parts = stream_title.split(' - ', 1)
                artist = parts[0].strip()
                title = parts[1].strip()

            self.current_media_info['artist'] = artist
            self.current_media_info['title'] = title
            
            # Atualiza título da janela
            display = f"{artist} - {title}" if artist else title
            self.setWindowTitle(f"{self.station_name} | {display}" if self.station_name else f"Reproduzindo: {display}")

            # Se estiver na tela de áudio (sem vídeo), atualiza o display
            if self.current_media_info.get('type') == 'music':
                self.show_default_audio_ui()

    def play_previous(self):
        if self.playlist and self.current_index > 0:
            self.current_index -= 1
            self.load_video(self.playlist[self.current_index])
            self.playlistWidget.setCurrentRow(self.current_index)

    def _parse_and_display_details(self, title, plot, icon_url, fanart_url):
        """Helper para parsear o plot e atualizar a sidebar de detalhes."""
        
        # Atualiza o fundo de tela
        self.set_fanart_background(fanart_url)

        # Limpa imagem e texto anteriores
        self.detailsImageLabel.hide()
        self.detailsImageLabel.clear()
        self.detailsTextLabel.clear()

        # Inicia download da imagem em background
        if icon_url:
            if icon_url.startswith('http'):
                threading.Thread(target=self.download_details_image, args=(icon_url,), daemon=True).start()
            elif os.path.exists(icon_url):
                self.set_details_image(QImage(icon_url))

        # --- Lógica de Parsing do Plot ---
        # Garante que [CR] seja tratado como quebra de linha antes de remover formatação
        plot_str = plot
        if isinstance(plot_str, bytes):
            plot_str = plot_str.decode('utf-8', errors='ignore')

        title_str = title
        if isinstance(title_str, bytes):
            title_str = title_str.decode('utf-8', errors='ignore')

        temp_plot = (plot_str or "").replace('[CR]', '\n')
        clean_plot = remove_kodi_formatting(temp_plot)
        clean_title = remove_kodi_formatting(title_str or "")
        
        details = {
            'Avaliação': '', 'Gênero': '', 'Lançamento': '', 'Ano': ''
        }
        synopsis_text = ""
        
        # Tenta extrair dados estruturados do plot (comum em plugins BR)
        lines = clean_plot.split('\n')
        remaining_plot_lines = []
        
        key_map = {
            'Avaliação': 'Avaliação', 'Rating': 'Avaliação',
            'Gênero': 'Gênero', 'Genre': 'Gênero',
            'Lançamento': 'Lançamento', 'Release': 'Lançamento', 'Data': 'Lançamento',
            'Ano': 'Ano', 'Year': 'Ano',
        }
        
        synopsis_keys = ['Sinopse', 'Plot', 'Description']

        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                
                if key in key_map:
                    details[key_map[key]] = value.strip()
                elif key in synopsis_keys:
                    # Se já tivermos uma sinopse, anexa a nova linha
                    if synopsis_text:
                        synopsis_text += '\n' + value.strip()
                    else:
                        synopsis_text = value.strip()
                else:
                    remaining_plot_lines.append(line)
            elif line.strip():
                remaining_plot_lines.append(line)

        # Se a sinopse não foi encontrada por uma chave explícita, o que sobrou é a sinopse.
        if not synopsis_text:
            synopsis_text = ' '.join(remaining_plot_lines).strip()
        else:
            # Se a sinopse foi encontrada, mas sobraram linhas, anexa-as.
            synopsis_text += ' ' + ' '.join(remaining_plot_lines).strip()
            synopsis_text = synopsis_text.strip()

        # --- Monta o HTML para exibição ---
        html_parts = [f"<h3 style='color: #ff4b4b;'>{clean_title}</h3>"]
        meta_html = [f"<b>{k}:</b> {v}" for k, v in details.items() if v]
        if meta_html:
            html_parts.append(f"<p style='color: #ddd; font-size: 13px;'>{' | '.join(meta_html)}</p>")
        
        if synopsis_text:
            plot_text = synopsis_text.replace('\n', '<br>') # Suporta quebras de linha
            plot_text = plot_text[:800] + "..." if len(plot_text) > 800 else plot_text
            html_parts.append(f"<p style='color: #eee; font-size: 14px;'>{plot_text}</p>")
            
        self.detailsTextLabel.setText("".join(html_parts))

        # Mostra a sidebar se tivermos qualquer informação
        if any(details.values()) or synopsis_text or icon_url or title:
            self.detailsWidget.setGeometry(0, 0, self.details_width, self.height())
            self.detailsWidget.show()
            self.detailsWidget.raise_()
            self.details_hide_timer.start(15000)

    def stop_video(self):
        self.mediaPlayer.stop()
        self.videoOutput.set_frame(None)

        # Limpa o fundo de tela ao parar
        self.set_fanart_background(None)
        
        # Fecha o buffer de stream para parar o download de dados imediatamente
        if self.stream_buffer:
            self.stream_buffer.close()
            self.stream_buffer = None
            
        # Esconde a sidebar de detalhes
        self.detailsWidget.hide()
        self.details_hide_timer.stop()
            
        # Notifica o bridge que o player parou (para plugins que monitoram isPlaying)
        kodi_bridge.MockXBMC.Player().stop()
        self.setWindowTitle("Player PyQt6 (Áudio + Vídeo + Zoom)")
        try:
            if hasattr(self, 'thread') and self.thread and self.thread.isRunning():
                self.thread.quit()
                self.worker.deleteLater()
        except (RuntimeError, AttributeError) as e:
            # Loga o erro para depuração e reseta a thread para evitar mais crashes.
            log_to_file(f"Erro ao parar a thread: {e}")
            self.thread = None # type: ignore

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
            
            # Se o item for "não-pasta" (isFolder=False), pode ser um link direto ou um item que precisa ser resolvido.
            # A lógica de resolução (run_plugin_action) já lida com isso.
            # A verificação abaixo é para links diretos que já vêm com metadados.
            if not plugin_data.get('isFolder') and not url.startswith("plugin://"):
                # Reconstrói metadados a partir do listitem do plugin
                media_info = {"title": item.text(), "type": "video"} # Fallback
                if 'listitem' in plugin_data:
                    li = plugin_data['listitem']
                    info = getattr(li, 'info', {})
                    art = getattr(li, 'art', {})
                    media_info = {
                        "title": info.get('title', plugin_data.get('label')),
                        "artist": info.get('artist'),
                        "plot": info.get('plot'),
                        "icon": art.get('icon') or art.get('thumb'),
                        "type": getattr(li, 'media_type', 'video')
                    }
                self.load_video(url, media_info)
            
            else:
                # Se for uma navegação normal de plugin, executa a ação
                self.run_plugin_action(url)
        elif row >= 0 and row < len(self.playlist):
            # Comportamento normal de arquivo local
            self.current_index = row
            self.load_video(self.playlist[row])

    def on_playlist_selection_changed(self, current, previous):
        """Atualiza a sidebar de detalhes quando o item selecionado na playlist muda."""
        if not current:
            self.detailsTextLabel.clear()
            self.detailsImageLabel.hide()
            self.detailsWidget.hide()
            return

        data = current.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        # Extrai metadados do item da lista
        title = remove_kodi_formatting(current.text())
        plot, icon_url, fanart_url = "", "", ""
        if isinstance(data, dict):
            if 'listitem' in data:
                li = data['listitem']
                info = getattr(li, 'info', {})
                art = getattr(li, 'art', {})
                plot = info.get('plot') or info.get('description') or ''
                icon_url = art.get('thumb') or art.get('icon') or art.get('poster')
                fanart_url = art.get('fanart')
        
        # Usa a função helper para parsear e exibir
        self._parse_and_display_details(title, plot, icon_url, fanart_url)

    def play_video(self):
        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.mediaPlayer.pause()
        else:
            self.mediaPlayer.play()

    def media_state_changed(self, state):
        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.playBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            # Inicia timer para esconder a sidebar de detalhes
            if not self.detailsWidget.isHidden():
                self.details_hide_timer.start(7000) # 7 segundos
        else:
            self.playBtn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            # Para o timer se o vídeo for pausado/parado
            self.details_hide_timer.stop()

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

    def open_settings_dialog(self):
        """Abre o diálogo de configurações de cache."""
        from modules.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        if dialog.exec():
            # Recarrega a memória local após salvar
            self.memory = load_memory()
            self.show_notification("Configurações", "Configurações de cache aplicadas com sucesso.")

    def handle_frame(self, frame):
        if frame.isValid():
            self.videoOutput.set_frame(frame.toImage())

    def handle_mouse_move(self, event):
        # Exibe a playlist se o mouse estiver a 50px da borda direita
        w = self.videoOutput.width()
        x = event.pos().x()
        
        # --- Lógica para sidebar de detalhes (esquerda) ---
        if x < 50:
            if self.detailsWidget.isHidden() and self.detailsTextLabel.text():
                self.details_hide_timer.stop() # Para o timer de esconder
                self.detailsWidget.setGeometry(0, 0, self.details_width, self.height())
                self.detailsWidget.show()
                self.detailsWidget.raise_()
        elif x > self.details_width:
            if not self.detailsWidget.isHidden():
                self.detailsWidget.hide()
        # ------------------------------------------------

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
        self.backgroundLabel.setGeometry(self.rect()) # Mantém o fundo do tamanho da janela
        if not self.playlistWidget.isHidden():
            self.playlistWidget.setGeometry(self.width() - self.playlist_width, 0, self.playlist_width, self.height())
        
        # Atualiza geometria da sidebar de detalhes
        if not self.detailsWidget.isHidden():
            self.detailsWidget.setGeometry(0, 0, self.details_width, self.height())
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
