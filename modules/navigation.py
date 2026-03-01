import streamlit as st
import os
import urllib.parse
import xml.etree.ElementTree as ET
import google_storage
from core.kodi_bridge import run_plugin
from core.utils import ADDONS_DIR, PLUGINS_REPO_DIR
from modules.utils import install_dependencies

def navigate_to(url, label="Home", dialog_answers=None):
    """Executa o plugin e atualiza o estado com os novos itens."""
    
    # --- Atualiza Histórico Recente (Home) ---
    if url and label and label != "Home" and not url.startswith("resume:") and not url.startswith("install://"):
        new_item = {'url': url, 'label': label}
        # Remove se já existir para mover para o topo (evita duplicatas)
        if 'recent_history' in st.session_state:
            st.session_state.recent_history = [i for i in st.session_state.recent_history if i['url'] != url]
            st.session_state.recent_history.insert(0, new_item)
            st.session_state.recent_history = st.session_state.recent_history[:10] # Mantém apenas os últimos 10
    
    # --- Lógica de Resume (Retomar execução com resposta do Dialog) ---
    if url.startswith("resume:select:"):
        try:
            idx = int(url.split(":")[-1])
            # Usa a URL atual (que gerou o dialog) para re-executar o plugin
            if st.session_state.current_url:
                current_label = st.session_state.history[-1][1] if st.session_state.history else "Voltar"
                navigate_to(st.session_state.current_url, current_label, dialog_answers=[idx])
        except Exception as e:
            st.error(f"Erro ao processar seleção: {e}")
        return
    
    if url.startswith("install://"):
        try:
            # Parse da URL: install://addon.id?zip=...&name=...
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            zip_url = query.get('zip', [None])[0]
            name = query.get('name', [parsed.netloc])[0]
            
            if not zip_url:
                st.error("URL de instalação inválida.")
                return

            with st.spinner(f"Baixando e instalando {name}..."):
                import requests, zipfile, io
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                r = requests.get(zip_url, headers=headers, timeout=60)
                r.raise_for_status()
                
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    z.extractall(ADDONS_DIR)
                
                st.success(f"✅ {name} instalado com sucesso!")
                st.info("Recarregue a página (F5) para ver o novo plugin na lista.")
        except Exception as e:
            st.error(f"❌ Erro ao instalar: {e}")
        return

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
        st.session_state.video_url = stream_url
        return

    # Se for plugin://, executa via bridge
    if url.startswith("plugin://"):
        # Limpa itens atuais preventivamente para evitar "fantasma" da interface antiga
        # se o carregamento falhar ou demorar.
        st.session_state.current_items = []
        
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
                result = run_plugin(entry_point, params, dialog_answers=dialog_answers)
                
                # Captura erro se houver
                st.session_state.last_error = result.get("error")
                # Captura título do diálogo se houver
                st.session_state.dialog_heading = result.get("dialog_heading")
                
                if result.get("dialog_heading"):
                    # O plugin pediu uma seleção (ex: escolher servidor)
                    st.session_state.current_items = result["items"]
                    # Não limpamos current_url para permitir o resume na mesma URL
                    st.session_state.video_url = None
                    return

                if result.get("dialog_input"):
                    # O plugin pediu input de texto
                    st.session_state.input_dialog = result["dialog_input"]
                    st.session_state.input_dialog_url = url # URL para retomar
                    st.rerun()
                    return

                if result.get("resolved_url"):
                    # É um vídeo para tocar
                    # Define preview e inicia reprodução direta (Autoplay)
                    st.session_state.preview_media = result
                    st.session_state.video_url = result["resolved_url"]
                else:
                    # É um diretório
                    st.session_state.current_items = result["items"]
                    st.session_state.current_url = url
                    st.session_state.video_url = None # Limpa vídeo anterior
            else:
                # Tenta verificar se é um Repositório (que não tem main.py)
                addon_xml = os.path.join(plugin_path, 'addon.xml')
                is_repo = False
                if os.path.exists(addon_xml):
                    try:
                        tree = ET.parse(addon_xml)
                        root = tree.getroot()
                        
                        # Procura extensão de repositório
                        for ext in root.findall('extension'):
                            if ext.get('point') == 'xbmc.addon.repository':
                                is_repo = True
                                # Tenta extrair a URL do XML de addons
                                dirs = ext.findall('dir')
                                if dirs:
                                    # Usa a última definição (geralmente a mais recente)
                                    target_dir = dirs[-1]
                                    info_node = target_dir.find('info')
                                    datadir_node = target_dir.find('datadir')
                                    
                                    if info_node is not None and info_node.text:
                                        info_url = info_node.text
                                        # Define URL base para downloads (datadir ou diretório do info)
                                        base_url = datadir_node.text if datadir_node is not None and datadir_node.text else os.path.dirname(info_url)
                                        if not base_url.endswith('/'): base_url += '/'

                                        with st.spinner(f"Lendo repositório: {info_url}..."):
                                            import requests
                                            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                                            r = requests.get(info_url, headers=headers, timeout=15)
                                            r.raise_for_status()
                                            
                                            remote_root = ET.fromstring(r.content)
                                            repo_items = []
                                            for addon in remote_root.findall('addon'):
                                                a_id = addon.get('id')
                                                a_ver = addon.get('version')
                                                a_name = addon.get('name')
                                                
                                                if not a_id or not a_ver:
                                                    continue
                                                
                                                if not a_name:
                                                    a_name = a_id
                                                
                                                # Monta URL do ZIP: base/id/id-version.zip
                                                zip_link = f"{base_url}{a_id}/{a_id}-{a_ver}.zip"
                                                safe_zip = urllib.parse.quote(zip_link)
                                                safe_name = urllib.parse.quote(a_name)
                                                
                                                repo_items.append({
                                                    'label': f"⬇️ {a_name} v{a_ver}",
                                                    'url': f"install://{a_id}?zip={safe_zip}&name={safe_name}",
                                                    'isFolder': False,
                                                    'art': {'icon': 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e1/Kodi_logo.svg/1024px-Kodi_logo.svg.png'}
                                                })
                                            st.session_state.current_items = repo_items
                                            st.session_state.current_url = url
                                            return
                    except Exception as e:
                        st.warning(f"Erro ao ler repositório: {e}")
                
                if not is_repo:
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