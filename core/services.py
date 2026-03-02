import threading
import os
import sys
import importlib.util
import xml.etree.ElementTree as ET
from core.utils import ADDONS_DIR
from core.kodi_bridge import setup_mocks, set_current_addon_id

# Registro de serviços rodando para evitar duplicatas
_running_services = {}

def start_service(addon_id):
    """Inicia o serviço (service.py) de um addon em uma thread separada."""
    if addon_id in _running_services:
        return # Já está rodando

    addon_path = os.path.join(ADDONS_DIR, addon_id)
    if not os.path.exists(addon_path):
        return

    # Procura pelo ponto de entrada do serviço
    service_file = None
    
    # 1. Tenta ler do addon.xml
    addon_xml = os.path.join(addon_path, 'addon.xml')
    if os.path.exists(addon_xml):
        try:
            tree = ET.parse(addon_xml)
            root = tree.getroot()
            for ext in root.findall('extension'):
                if ext.get('point') == 'xbmc.service':
                    lib = ext.get('library')
                    if lib:
                        candidate = os.path.join(addon_path, lib)
                        if os.path.exists(candidate):
                            service_file = candidate
                            break
        except:
            pass

    # 2. Fallback para service.py
    if not service_file:
        candidate = os.path.join(addon_path, "service.py")
        if os.path.exists(candidate):
            service_file = candidate
            
    if not service_file:
        return

    print(f"[SERVICE] Iniciando serviço para {addon_id}...")
    
    def service_runner():
        setup_mocks()
        
        # Define o ID do addon atual na thread local
        set_current_addon_id(addon_id)
        
        # Simula sys.argv para o serviço (evita erros se o plugin tentar acessar)
        sys.argv = [service_file]
        
        # Adiciona o caminho do addon ao sys.path
        if addon_path not in sys.path:
            sys.path.insert(0, addon_path)
            # Adiciona libs internas também
            for sub in ['lib', 'resources/lib']:
                lib_path = os.path.join(addon_path, sub)
                if os.path.exists(lib_path) and lib_path not in sys.path:
                    sys.path.insert(0, lib_path)
        
        try:
            # Carrega e executa o serviço
            spec = importlib.util.spec_from_file_location("__main__", service_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules["__main__"] = module
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[SERVICE] Erro no serviço {addon_id}: {e}")
        finally:
            # Remove do registro se parar (embora serviços geralmente rodem em loop)
            if addon_id in _running_services:
                del _running_services[addon_id]

    t = threading.Thread(target=service_runner, name=f"Service-{addon_id}", daemon=True)
    _running_services[addon_id] = t
    t.start()

def check_and_start_services():
    """Verifica addons instalados e inicia seus serviços se necessário."""
    # Lista de addons conhecidos que precisam de serviço
    # No futuro, isso poderia ler todos os addon.xml
    known_services = [
        'repository.elementumorg',
        'plugin.video.elementum' # O Elementum principal também tem um serviço binário complexo
    ]
    
    for addon_id in known_services:
        if os.path.exists(os.path.join(ADDONS_DIR, addon_id)):
            start_service(addon_id)
