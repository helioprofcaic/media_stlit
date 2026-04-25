import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSlider, 
                             QLabel, QPushButton, QFormLayout, QSpinBox)
from PyQt6.QtCore import Qt
from core.utils import load_memory, save_memory

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🚀 Configurações de Cache (Estilo Kodi)")
        self.setFixedWidth(400)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        # Buffer Size
        self.buffer_size_spin = QSpinBox()
        self.buffer_size_spin.setRange(16, 128)
        self.buffer_size_spin.setSuffix(" MB")
        form_layout.addRow("Tamanho do Buffer:", self.buffer_size_spin)
        
        # Read Factor
        self.read_factor_spin = QSpinBox()
        self.read_factor_spin.setRange(1, 20)
        self.read_factor_spin.setSuffix(" x")
        form_layout.addRow("Fator de Leitura:", self.read_factor_spin)
        
        # Chunk Size
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(32, 1024)
        self.chunk_size_spin.setSuffix(" KB")
        self.chunk_size_spin.setSingleStep(32)
        form_layout.addRow("Tamanho do Bloco:", self.chunk_size_spin)
        
        layout.addLayout(form_layout)
        
        # Informativo
        info_label = QLabel("\nNota: O aumento do buffer melhora a estabilidade em conexões instáveis, "
                            "especialmente para vídeos H265/FHD.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(info_label)
        
        # Botões
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Salvar e Aplicar")
        self.save_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 5px;")
        self.save_btn.clicked.connect(self.save_settings)
        
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def load_settings(self):
        memory = load_memory()
        cache_config = memory.get('cache_config', {})
        
        self.buffer_size_spin.setValue(cache_config.get('buffer_size_mb', 64))
        self.read_factor_spin.setValue(cache_config.get('read_factor', 4))
        self.chunk_size_spin.setValue(cache_config.get('chunk_size_kb', 64))

    def save_settings(self):
        memory = load_memory()
        memory['cache_config'] = {
            'buffer_size_mb': self.buffer_size_spin.value(),
            'read_factor': self.read_factor_spin.value(),
            'chunk_size_kb': self.chunk_size_spin.value()
        }
        save_memory(memory)
        self.accept()
