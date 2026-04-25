import sys
import os
import subprocess

# Adiciona o diretório atual ao path para que os módulos (core, etc.) sejam encontrados
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from video_player import VideoPlayer, PYQT_AVAILABLE, install_pyqt

def main():
    """Ponto de entrada para a aplicação de desktop."""
    print("[LOADER] Iniciando o Player Desktop...")

    # Verifica se o PyQt6 está instalado. Se não, oferece a instalação.
    if not PYQT_AVAILABLE:
        print("[LOADER] PyQt6 não encontrado. Tentando instalar...")
        install_pyqt()
        # A função install_pyqt encerra o script, pedindo para o usuário rodar novamente.
        return

    # Cria e executa a aplicação PyQt
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()