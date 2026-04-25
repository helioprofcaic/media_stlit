import os
import datetime
import json
import sys
import re
import subprocess

# --- Configuração de Dados e Logs (Memória do Player) ---
# O diretório base é dois níveis acima deste arquivo (core/utils.py -> core -> Dev)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

LOG_FILE = os.path.join(DATA_DIR, 'player.log')
MEMORY_FILE = os.path.join(DATA_DIR, 'memory.json')
PLAYLIST_FILE = os.path.join(DATA_DIR, 'last_playlist.json')
ADDONS_DIR = os.path.join(DATA_DIR, 'addons')
PLUGINS_REPO_DIR = os.path.join(BASE_DIR, 'plugin')

if not os.path.exists(PLUGINS_REPO_DIR):
    os.makedirs(PLUGINS_REPO_DIR)

if not os.path.exists(ADDONS_DIR):
    os.makedirs(ADDONS_DIR)

def log_to_file(msg):
    """Escreve mensagem no arquivo de log com timestamp."""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass

def remove_kodi_formatting(text):
    """Remove as tags de formatação do Kodi ([B], [COLOR], etc.) de uma string."""
    if not isinstance(text, str):
        return text
    # Regex mais robusta para remover tags como [B], [/B], [COLOR xxx], [/COLOR], etc.
    # Agora lida com tags coladas [B][COLOR] e tags sem espaço.
    # Adicionado [CR] que o Kodi usa para Carriage Return.
    clean_text = re.sub(r'\[/?(?:B|I|COLOR|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|SUB|SUP|FADE|SCROLL|LEFT|RIGHT|CENTER|JUSTIFY|font|char|CR|COLOR)\b[^\]]*\]', '', text, flags=re.IGNORECASE)
    # Remove espaços duplos que podem surgir após a remoção de tags
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def load_memory():
    """Carrega configurações salvas."""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log_to_file(f"Erro ao carregar memória: {e}")
    return {
        "recent_plugins": [], 
        "last_plugin": "", 
        "last_directory": "", 
        "last_video": "",
        "cache_config": {
            "buffer_size_mb": 64,   # MB (Padrão 64, suporta até 128)
            "read_factor": 4,      # Fator de download (Padrão 4x, suporta até 20x)
            "chunk_size_kb": 64    # KB (Padrão 64, suporta até 1024)
        }
    }

def save_memory(memory):
    """Salva configurações no disco."""
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(memory, f, indent=4)
    except Exception as e:
        log_to_file(f"Erro ao salvar memória: {e}")

def install_pyqt():
    """Função auxiliar para instalar PyQt6 via pip usando interface Tkinter básica"""
    import tkinter as tk
    from tkinter import messagebox
    
    root = tk.Tk()
    root.withdraw() # Esconde a janela principal

    answer = messagebox.askyesno(
        "Instalação Necessária", 
        "Para reproduzir Áudio e Vídeo com qualidade e Zoom,\n"
        "precisamos da biblioteca 'PyQt6'.\n\n"
        "Deseja instalá-la automaticamente agora? (aprox. 50-60MB)"
    )
    
    if answer:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "PyQt6"])
            messagebox.showinfo("Sucesso", "Instalação concluída!\nO programa será fechado. Por favor, execute-o novamente.")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha na instalação: {e}")
    
    sys.exit()