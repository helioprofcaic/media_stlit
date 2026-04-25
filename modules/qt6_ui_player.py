import os
try:
    from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                                 QSlider, QLabel, QStyle, QListWidget)
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QIcon
except ImportError:
    pass

from video_widget import VideoOutputWidget

class VideoPlayerUI:
    def setup_ui(self, window):
        """Constrói a interface gráfica na janela principal fornecida."""
        
        # Configura o ícone da janela principal
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'icon.png')
        if os.path.exists(icon_path):
            window.setWindowIcon(QIcon(icon_path))

        # --- Interface Gráfica (Layout) ---
        
        # Fundo de tela (camada inferior)
        window.backgroundLabel = QLabel(window)
        window.backgroundLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        window.backgroundLabel.setStyleSheet("background-color: #1a1a1a;")

        # Playlist Widget (Overlay)
        window.playlistWidget = QListWidget(window)
        window.playlistWidget.hide()
        window.playlistWidget.setStyleSheet("background-color: rgba(0, 0, 0, 0.8); color: white; border: none; font-size: 14px;")
        
        # Widget de Detalhes (Sidebar Esquerda)
        window.detailsWidget = QWidget(window)
        window.detailsWidget.hide()
        window.detailsWidget.setStyleSheet("background-color: rgba(0, 0, 0, 0.8); border: none;")
        
        details_layout = QVBoxLayout(window.detailsWidget)
        details_layout.setContentsMargins(10, 10, 10, 10)
        
        window.detailsImageLabel = QLabel()
        window.detailsImageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        window.detailsImageLabel.setMinimumHeight(200)
        window.detailsImageLabel.hide()
        details_layout.addWidget(window.detailsImageLabel)

        window.detailsTextLabel = QLabel()
        window.detailsTextLabel.setStyleSheet("color: white; font-size: 14px;")
        window.detailsTextLabel.setWordWrap(True)
        window.detailsTextLabel.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        details_layout.addWidget(window.detailsTextLabel)
        details_layout.addStretch()

        # Timer para esconder a sidebar de detalhes
        window.details_hide_timer = QTimer(window)
        window.details_hide_timer.setSingleShot(True)
        window.details_hide_timer.timeout.connect(window.detailsWidget.hide)

        # Widget Central e Layout Principal
        central_widget = QWidget()
        window.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Configuração inicial da geometria do fundo
        window.backgroundLabel.setGeometry(window.rect())
        window.backgroundLabel.lower()
        
        # Widget de Saída de Vídeo (Substitui QVideoWidget e Overlay)
        # Passamos os callbacks definidos na classe VideoPlayer (window)
        window.videoOutput = VideoOutputWidget(window.toggle_fullscreen, window.handle_mouse_move, window.play_video)
        layout.addWidget(window.videoOutput)
        
        # Layout de Controles
        controls_layout = QHBoxLayout()
        layout.addLayout(controls_layout)

        # Criação dos Botões
        window.openBtn = QPushButton("Abrir Vídeo")
        controls_layout.addWidget(window.openBtn)

        window.pluginBtn = QPushButton("Carregar Plugin")
        controls_layout.addWidget(window.pluginBtn)

        window.repoBtn = QPushButton("Repositórios")
        controls_layout.addWidget(window.repoBtn)

        window.prevBtn = QPushButton()
        window.prevBtn.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        controls_layout.addWidget(window.prevBtn)

        window.playBtn = QPushButton()
        window.playBtn.setEnabled(False)
        window.playBtn.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        controls_layout.addWidget(window.playBtn)

        window.stopBtn = QPushButton()
        window.stopBtn.setEnabled(False)
        window.stopBtn.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        controls_layout.addWidget(window.stopBtn)

        window.nextBtn = QPushButton()
        window.nextBtn.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        controls_layout.addWidget(window.nextBtn)

        # Botão de Configurações (Ajustes de Cache)
        window.settingsBtn = QPushButton()
        window.settingsBtn.setIcon(window.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        window.settingsBtn.setToolTip("Configurações de Cache")
        controls_layout.addWidget(window.settingsBtn)

        # Slider de Posição (Seekbar)
        window.positionSlider = QSlider(Qt.Orientation.Horizontal)
        window.positionSlider.setRange(0, 0)
        controls_layout.addWidget(window.positionSlider)

        # Label de Tempo
        window.timeLabel = QLabel("00:00")
        controls_layout.addWidget(window.timeLabel)

        # Slider de Volume
        window.volumeSlider = QSlider(Qt.Orientation.Horizontal)
        window.volumeSlider.setRange(0, 100)
        window.volumeSlider.setValue(70)
        window.volumeSlider.setFixedWidth(100)
        controls_layout.addWidget(QLabel("Vol:"))
        controls_layout.addWidget(window.volumeSlider)