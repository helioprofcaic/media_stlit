import re
import os
import sys
import xml.etree.ElementTree as ET
import importlib.util
import subprocess
import streamlit as st

# --- Configuração de Bibliotecas Locais (Fallback) ---
LOCAL_LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs")

def remove_kodi_formatting(text):
    """Remove tags de formatação do Kodi ([B], [COLOR], etc)."""
    if not isinstance(text, str):
        return text
    # Regex para remover tags como [B], [/B], [COLOR xxx], [/COLOR], [I], [/I] etc.
    # A regex é case-insensitive.
    # Adicionado \b para garantir que não pegue palavras que contenham as letras das tags.
    clean_text = re.sub(r'\[/?(B|I|COLOR|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|SUB|SUP|FADE|SCROLL|LEFT|RIGHT|CENTER|JUSTIFY|font|char|CR)\b[^\]]*\]', '', text, flags=re.IGNORECASE)
    return clean_text

def install_dependencies(plugin_path):
    """Lê o addon.xml e tenta instalar dependências Python via pip."""
    addon_xml = os.path.join(plugin_path, 'addon.xml')
    if not os.path.exists(addon_xml):
        return

    try:
        tree = ET.parse(addon_xml)
        root = tree.getroot()
        requires = root.find('requires')
        if requires is None:
            return

        packages_to_install = []
        
        # Mapeamento de nomes do Kodi para PyPI
        KODI_TO_PIP = {
            'script.module.requests': 'requests',
            'script.module.beautifulsoup4': 'beautifulsoup4',
            'script.module.urllib3': 'urllib3',
            'script.module.six': 'six',
            'script.module.future': 'future',
            'script.module.kodi-six': None,
            'script.module.simplejson': None, # Usa json nativo
            'script.module.mechanize': 'mechanize',
            'script.module.cloudscraper': 'cloudscraper',
            'script.module.pycryptodome': 'pycryptodome',
            'script.module.netunblock': None,
            'script.module.resolveurl': None,
            'script.module.routing': None, # Mockado no bridge
            'script.module.urlresolver': None,
            'script.module.metahandler': None,
            'script.module.inputstreamhelper': None,
        }

        for import_tag in requires.findall('import'):
            addon_id = import_tag.get('addon')
            if not addon_id or addon_id == 'xbmc.python':
                continue
            
            pip_package = None
            # Verifica se está no mapa (pode ser None para ignorar)
            if addon_id in KODI_TO_PIP:
                pip_package = KODI_TO_PIP[addon_id]
            # Se não estiver no mapa, tenta inferir removendo o prefixo
            elif addon_id.startswith('script.module.'):
                pip_package = addon_id.replace('script.module.', '')
            
            if pip_package:
                # Verifica se já está instalado
                # Mapeia nome do pacote pip para nome do import real
                PIP_IMPORTS = {
                    'beautifulsoup4': 'bs4',
                    'pycryptodome': 'Crypto',
                    'kodi-six': 'kodi_six',
                }
                import_name = PIP_IMPORTS.get(pip_package, pip_package)
                
                # Se já estiver carregado (ex: mocks do bridge), ignora para evitar erro de spec
                if import_name in sys.modules:
                    continue
                
                spec = importlib.util.find_spec(import_name)
                
                if spec is None:
                    packages_to_install.append(pip_package)

        if packages_to_install:
            with st.spinner(f"Instalando dependências: {', '.join(packages_to_install)}..."):
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages_to_install)
                    importlib.invalidate_caches()
                    st.toast(f"Dependências instaladas!", icon="✅")
                except subprocess.CalledProcessError:
                    # Fallback: Tenta instalar no diretório local (libs)
                    try:
                        if not os.path.exists(LOCAL_LIB_DIR):
                            os.makedirs(LOCAL_LIB_DIR)
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "--target", LOCAL_LIB_DIR] + packages_to_install)
                        importlib.invalidate_caches()
                        st.toast(f"Dependências instaladas localmente!", icon="✅")
                    except subprocess.CalledProcessError:
                        st.warning(f"Não foi possível instalar algumas dependências automaticamente: {packages_to_install}")
            
    except Exception as e:
        print(f"Erro ao verificar dependências: {e}")