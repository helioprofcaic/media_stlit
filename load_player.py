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

    # Pega o caminho do executável do venv passado pelo .bat, ou usa o padrão se não for passado
    venv_python_executable = sys.argv[1] if len(sys.argv) > 1 else sys.executable

    # Cria e executa a aplicação PyQt
    app = QApplication(sys.argv)
    # Passa o caminho do executável para o player
    player = VideoPlayer(python_executable=venv_python_executable)
    player.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()