import streamlit as st
import os
import sys
import subprocess
import importlib.util
import xml.etree.ElementTree as ET
import urllib.parse
import google_storage

# Adiciona o diretório atual ao path para importar os módulos core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.kodi_bridge import run_plugin
from core.utils import PLUGINS_REPO_DIR, ADDONS_DIR

st.set_page_config(page_title="Streamlit Media Player", layout="wide")

# --- Inicialização de Estado ---
if 'history' not in st.session_state:
    st.session_state.history = []  # Pilha de navegação [(url, label)]
if 'current_url' not in st.session_state:
    st.session_state.current_url = None
if 'current_items' not in st.session_state:
    st.session_state.current_items = []
if 'preview_media' not in st.session_state:
    st.session_state.preview_media = None # Armazena metadados antes do play

# --- Funções Auxiliares ---

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
            'script.module.kodi-six': 'kodi-six',
            'script.module.simplejson': 'simplejson',
            'script.module.mechanize': 'mechanize',
            'script.module.cloudscraper': 'cloudscraper',
            'script.module.pycryptodome': 'pycryptodome',
            'script.module.netunblock': None,
            'script.module.resolveurl': None,
            'script.module.urlresolver': None,
            'script.module.metahandler': None,
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
                spec = importlib.util.find_spec(pip_package)
                # Tratamento para pacotes com nomes de import diferentes
                if pip_package == 'beautifulsoup4':
                    spec = importlib.util.find_spec('bs4')
                if pip_package == 'pycryptodome':
                    spec = importlib.util.find_spec('Crypto')
                
                if spec is None:
                    packages_to_install.append(pip_package)

        if packages_to_install:
            with st.spinner(f"Instalando dependências: {', '.join(packages_to_install)}..."):
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages_to_install)
                    importlib.invalidate_caches()
                    st.toast(f"Dependências instaladas!", icon="✅")
                except subprocess.CalledProcessError:
                    st.warning(f"Não foi possível instalar algumas dependências automaticamente: {packages_to_install}")
            
    except Exception as e:
        print(f"Erro ao verificar dependências: {e}")

def navigate_to(url, label="Home"):
    """Executa o plugin e atualiza o estado com os novos itens."""
    
    # --- Suporte a Google Drive (Navegação de Pastas) ---
    if url.startswith("gdrive_folder://"):
        folder_id = url.replace("gdrive_folder://", "")
        if folder_id == "root":
            folder_id = None # Usa o ID configurado no secrets
            
        with st.spinner("Listando arquivos do Drive..."):
            files = google_storage.list_files_with_link(folder_id)
            
            drive_items = []
            if files:
                for f in files:
                    mime = f.get('mimeType', '')
                    # Pastas
                    if mime == 'application/vnd.google-apps.folder':
                        drive_items.append({
                            'label': f.get('name'),
                            'url': f"gdrive_folder://{f.get('id')}",
                            'isFolder': True,
                            'art': {'icon': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/Folder-icon-yellow.svg/1024px-Folder-icon-yellow.svg.png'}
                        })
                    # Arquivos de Mídia
                    elif 'video' in mime or 'audio' in mime:
                        drive_items.append({
                            'label': f.get('name'),
                            'url': f"gdrive://{f.get('id')}",
                            'isFolder': False,
                            'art': {'thumb': f.get('thumbnailLink')}
                        })
                
                # Ordena: Pastas primeiro, depois nome
                drive_items.sort(key=lambda x: (not x['isFolder'], x['label'].lower()))
            
            st.session_state.current_items = drive_items
            st.session_state.current_url = url
            st.session_state.video_url = None
        return

    # --- Suporte a Google Drive ---
    if url.startswith("gdrive://"):
        file_id = url.replace("gdrive://", "")
        # Gera link direto de streaming (requer que o arquivo esteja como 'Qualquer pessoa com o link' ou autenticado)
        stream_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        st.session_state.preview_media = {
            "resolved_url": stream_url,
            "media_info": {"title": label, "type": "video", "icon": "https://upload.wikimedia.org/wikipedia/commons/d/da/Google_Drive_logo.png"}
        }
        st.session_state.video_url = None
        return

    # Se for plugin://, executa via bridge
    if url.startswith("plugin://"):
        try:
            # Identifica o caminho físico do plugin
            plugin_id = url.replace("plugin://", "").split("/")[0]
            
            # Procura em addons instalados ou pasta de desenvolvimento
            plugin_path = os.path.join(ADDONS_DIR, plugin_id)
            if not os.path.exists(plugin_path):
                plugin_path = os.path.join(PLUGINS_REPO_DIR, plugin_id)
            
            # Verifica e instala dependências antes de executar
            install_dependencies(plugin_path)
            
            entry_point = os.path.join(plugin_path, "main.py")
            if not os.path.exists(entry_point):
                # Tenta default.py se main.py não existir
                entry_point = os.path.join(plugin_path, "default.py")
            
            if os.path.exists(entry_point):
                # Executa a ponte
                # Extrai parâmetros da URL
                params = url
                result = run_plugin(entry_point, params)
                
                if result.get("resolved_url"):
                    # É um vídeo para tocar
                    # NÃO define video_url direto (evita autoplay). Define preview.
                    st.session_state.preview_media = result
                    st.session_state.video_url = None 
                else:
                    # É um diretório
                    st.session_state.current_items = result["items"]
                    st.session_state.current_url = url
                    st.session_state.video_url = None # Limpa vídeo anterior
            else:
                st.error(f"Plugin não encontrado em: {plugin_path}")
        except Exception as e:
            st.error(f"Erro ao executar plugin: {e}")

def go_back():
    if len(st.session_state.history) > 1:
        st.session_state.history.pop() # Remove atual
        prev_url, prev_label = st.session_state.history[-1]
        navigate_to(prev_url, prev_label)
    else:
        st.session_state.history = []
        st.session_state.current_items = []
        st.session_state.current_url = None
    st.session_state.preview_media = None

# --- Interface ---

st.title("📺 Media Player Web")

# Sidebar: Lista de Plugins Instalados
with st.sidebar:
    st.header("Fonte de Mídia")
    source_mode = st.radio("Escolha a origem:", ["Plugins Kodi", "Google Drive", "Arquivos Locais"])
    
    if source_mode == "Plugins Kodi":
        plugins = []
        # Escaneia pastas
        for d in [ADDONS_DIR, PLUGINS_REPO_DIR]:
            if os.path.exists(d):
                for item in os.listdir(d):
                    if os.path.isdir(os.path.join(d, item)) and os.path.exists(os.path.join(d, item, 'addon.xml')):
                        plugins.append(item)
        
        selected_plugin = st.selectbox("Escolha um Plugin", ["Selecione..."] + list(set(plugins)))
        
        if st.button("Carregar Plugin"):
            if selected_plugin and selected_plugin != "Selecione...":
                start_url = f"plugin://{selected_plugin}/"
                st.session_state.history = [(start_url, selected_plugin)]
                navigate_to(start_url)

    elif source_mode == "Google Drive":
        if st.button("📂 Carregar Drive"):
            # Inicia navegação pela raiz
            start_url = "gdrive_folder://root"
            st.session_state.history = [(start_url, "Google Drive")]
            navigate_to(start_url, "Google Drive")
            st.rerun()
        
    elif source_mode == "Arquivos Locais":
        st.info("Navegue pelos arquivos e pastas do computador onde o servidor está rodando.")
        if st.button("📂 Iniciar Explorador Local"):
            local_explorer_id = "plugin.video.local_explorer"
            # Verifica se o plugin existe
            if os.path.exists(os.path.join(ADDONS_DIR, local_explorer_id)) or \
               os.path.exists(os.path.join(PLUGINS_REPO_DIR, local_explorer_id)):
                
                start_url = f"plugin://{local_explorer_id}/"
                st.session_state.history = [(start_url, "Arquivos Locais")]
                navigate_to(start_url, "Arquivos Locais")
            else:
                st.error("O plugin 'local_explorer' não foi encontrado. Instale-o pelos repositórios.")

        with st.expander("📤 Upload de Arquivo"):
            uploaded_file = st.file_uploader("Enviar Mídia", type=['mp4', 'mkv', 'avi', 'mp3', 'wav'])
            if uploaded_file is not None:
                if st.button("Confirmar Upload"):
                    # Determina a pasta de destino baseada na navegação atual
                    target_folder = None
                    if st.session_state.current_url and st.session_state.current_url.startswith("gdrive_folder://"):
                        target_folder = st.session_state.current_url.replace("gdrive_folder://", "")
                        if target_folder == "root": target_folder = None

                    with st.spinner("Enviando para o Google Drive..."):
                        fid = google_storage.upload_file(uploaded_file, uploaded_file.name, folder_id=target_folder)
                        if fid:
                            st.success("Upload concluído com sucesso!")
                        else:
                            st.error("Falha no envio.")
        
        st.markdown("---")
        with st.expander("🔧 Diagnóstico de Conexão"):
            if st.button("Testar Acesso ao Drive"):
                with st.spinner("Verificando credenciais..."):
                    service = google_storage.get_drive_service()
                    if service:
                        st.success("✅ Conexão estabelecida!")
                        fid = google_storage.get_folder_id()
                        st.caption(f"Pasta Raiz: `{fid}`" if fid else "⚠️ Pasta Raiz não configurada")
                    else:
                        st.error("❌ Falha na conexão.")

# Área Principal

# --- 1. Breadcrumbs (Navegação) Moderno ---
if st.session_state.history:
    # Função para limpar nomes técnicos de plugins
    def clean_label(label):
        if label.startswith("plugin."):
            return label.split(".")[-1].replace("_", " ").title()
        return label

    path_labels = [clean_label(h[1]) for h in st.session_state.history]
    
    col_nav_1, col_nav_2 = st.columns([0.8, 15])
    with col_nav_1:
        if st.button("⬅️", help="Voltar", use_container_width=True):
            go_back()
            st.rerun()
    with col_nav_2:
        # Monta HTML para breadcrumbs estilizados
        html_parts = []
        for i, label in enumerate(path_labels):
            is_last = (i == len(path_labels) - 1)
            if is_last:
                html_parts.append(f"<span style='font-weight:bold; color:rgb(255, 75, 75); background:rgba(255, 75, 75, 0.1); padding:2px 8px; border-radius:6px;'>{label}</span>")
            else:
                html_parts.append(f"<span style='color:rgba(128, 128, 128, 0.8);'>{label}</span>")
        
        separator = "<span style='margin:0 8px; color:#ddd;'>›</span>"
        st.markdown(f"<div style='display:flex; align-items:center; height:36px; font-family:sans-serif; font-size:16px;'>{separator.join(html_parts)}</div>", unsafe_allow_html=True)

# --- 2. Área de Reprodução e Pré-visualização ---

# Caso A: Player Ativo
if st.session_state.get('video_url'):
    with st.container(border=True):
        # Tenta obter título dos metadados salvos
        display_title = "Reproduzindo Agora"
        icon = "🍿"
        if st.session_state.get('preview_media'):
            info = st.session_state.preview_media.get('media_info', {})
            if info.get('title'):
                display_title = info['title']
                if info.get('artist'):
                    display_title = f"{info['artist']} - {display_title}"
            
            media_type = info.get('type', 'video')
            if media_type == 'music':
                icon = "🎵"
            elif media_type == 'video':
                icon = "🎬"
        
        st.subheader(f"{icon} {display_title}")
        url = st.session_state.video_url
        
        if "|" in url:
            clean_url = url.split("|")[0]
            headers = url.split("|")[1]
            st.warning(f"⚠️ Requer headers: {headers}")
            url = clean_url

        st.video(url, autoplay=True)
        
        if st.button("⏹️ Parar Reprodução", use_container_width=True):
            st.session_state.video_url = None
            st.rerun()
            
        with st.expander("📱 Assistir no Celular"):
            qr_target = url
            if "|" in qr_target:
                qr_target = qr_target.split("|")[0]
            
            if qr_target.startswith("http"):
                encoded_url = urllib.parse.quote(qr_target)
                qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_url}"
                c1, c2 = st.columns([1, 3])
                c1.image(qr_api, width=150)
                c2.info("Escaneie para abrir o vídeo no celular.")
                c2.code(qr_target, language="text")
            else:
                st.warning("Arquivo local. Não acessível via QR Code.")

# Caso B: Pré-visualização (Item Selecionado)
elif st.session_state.get('preview_media'):
    media = st.session_state.preview_media
    with st.container(border=True):
        info = media.get('media_info', {})
        
        col_prev_1, col_prev_2 = st.columns([1, 3])
        with col_prev_1:
            icon_url = info.get('icon') or "https://upload.wikimedia.org/wikipedia/commons/thumb/2/21/Speaker_Icon.svg/1024px-Speaker_Icon.svg.png"
            if icon_url.startswith("http") or os.path.exists(icon_url):
                st.image(icon_url, width=100)
            else:
                st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/2/21/Speaker_Icon.svg/1024px-Speaker_Icon.svg.png", width=100)
                
        with col_prev_2:
            title = info.get('title', 'Pronto para reproduzir')
            media_type = info.get('type', 'video')
            
            icon = "🎬" # default video
            if media_type == 'music':
                icon = "🎵"
            elif media_type == 'picture':
                icon = "🖼️"
            
            st.markdown(f"### {icon} {title}")
            
            if info.get('artist'):
                st.write(f"**Artista:** {info['artist']}")
            if info.get('plot'):
                st.caption(info['plot'])
            elif not info:
                st.write("O arquivo foi resolvido e está pronto.")
            
            if st.button("▶️ INICIAR REPRODUÇÃO", type="primary", use_container_width=True):
                st.session_state.video_url = media["resolved_url"]
                st.session_state.video_drm = media.get("drm_info")
                st.rerun()
            
            if st.button("Cancelar", use_container_width=True):
                st.session_state.preview_media = None
                st.rerun()
            
            with st.expander("📱 Assistir no Celular"):
                media_url = media["resolved_url"]
                qr_target = media_url
                if "|" in qr_target:
                    qr_target = qr_target.split("|")[0]
                
                if qr_target and qr_target.startswith("http"):
                    encoded_url = urllib.parse.quote(qr_target)
                    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_url}"
                    c1, c2 = st.columns([1, 3])
                    c1.image(qr_api, width=150)
                    c2.info("Escaneie para abrir o vídeo no celular.")
                    c2.code(qr_target, language="text")
                else:
                    st.warning("Arquivo local. Não acessível via QR Code.")

# --- 3. Navegador de Arquivos (Expansível) ---
if st.session_state.history:
    items = st.session_state.current_items
    # Fecha a lista se estiver vendo vídeo ou preview para focar no conteúdo
    is_viewing_content = (st.session_state.get('video_url') is not None) or (st.session_state.get('preview_media') is not None)
    
    with st.expander("📂 Navegador de Arquivos", expanded=not is_viewing_content):
        if not items:
            st.info(f"Pasta vazia ou erro ao carregar.\nURL: {st.session_state.current_url}")
        
        for idx, item in enumerate(items):
            # Layout em grid para ficar mais compacto e moderno
            col1, col2 = st.columns([0.5, 4])
            
            # Ícone
            icon = item.get('art', {}).get('thumb') or item.get('art', {}).get('icon')
            with col1:
                if icon and (icon.startswith('http') or os.path.exists(icon)):
                    st.image(icon, width=40)
                else:
                    st.write("📁" if item['isFolder'] else "🎬")
                
            # Botão
            label = item['label']
            if col2.button(label, key=f"btn_{idx}", use_container_width=True):
                new_url = item['url']
                st.session_state.history.append((new_url, label))
                navigate_to(new_url, label)
                st.rerun()
else:
    st.info("👈 Selecione um plugin na barra lateral para começar.")