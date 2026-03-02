import streamlit as st
import os
import urllib.parse
import xml.etree.ElementTree as ET
import google_storage
import gzip
import io
import re
from core.kodi_bridge import run_plugin
from core.utils import ADDONS_DIR, PLUGINS_REPO_DIR
from modules.utils import install_dependencies

def navigate_to(url, label="Home", dialog_answers=None):
    """Executa o plugin e atualiza o estado com os novos itens."""
    print(f"[NAV] Navigating to: {url} (Label: {label})")
    
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
            # Usa a URL pendente (que gerou o dialog) se existir, caso contrário usa a atual
            resume_url = st.session_state.get('pending_action_url', st.session_state.current_url)
            if resume_url:
                # Limpa o player visualmente enquanto processa a seleção para dar feedback
                st.session_state.video_url = None
                current_label = st.session_state.history[-1][1] if st.session_state.history else "Voltar"
                navigate_to(resume_url, current_label, dialog_answers=[idx])
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
                import requests, zipfile
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
        
        try:
            # Identifica o caminho físico do plugin
            plugin_id = url.replace("plugin://", "").split("/")[0]
            
            # --- PROTEÇÃO DE CONTEÚDO ADULTO ---
            restricted_keywords = ['erome', 'xvideos', 'tube8', 'pornhub', 'brazzers', 'adult', 'xxx', 'sex', '18+']
            if any(k in plugin_id.lower() for k in restricted_keywords):
                if not st.session_state.get('adult_unlocked', False):
                    st.session_state.password_required = True
                    st.session_state.pending_password_url = url
                    st.session_state.pending_password_label = label
                    st.rerun()
                    return
            # -----------------------------------

            # --- FALLBACK YOUTUBE (Se não instalado) ---
            if plugin_id == "plugin.video.youtube":
                is_installed = os.path.exists(os.path.join(ADDONS_DIR, plugin_id)) or \
                               os.path.exists(os.path.join(PLUGINS_REPO_DIR, plugin_id))
                if not is_installed:
                    print(f"[NAV] YouTube plugin missing. Handling URL natively: {url}")
                    
                    # Extrai ID de vídeo
                    # Padrões: /play/?video_id=ID, /?action=play_video&videoid=ID
                    match_vid = re.search(r'(?:video_id|videoid)=([^&]+)', url)
                    if match_vid:
                        video_id = match_vid.group(1)
                        yt_url = f"https://www.youtube.com/watch?v={video_id}"
                        st.session_state.preview_media = {
                            "resolved_url": yt_url,
                            "media_info": {"title": label, "type": "video", "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/YouTube_full-color_icon_%282017%29.svg/256px-YouTube_full-color_icon_%282017%29.svg.png"}
                        }
                        st.session_state.video_url = yt_url
                        return

                    # Extrai ID de Playlist
                    # Padrão: /playlist/ID/
                    path_from_url = urllib.parse.urlparse(url).path
                    match_pl = re.search(r'/playlist/([^/]+)', path_from_url)
                    if match_pl:
                        pl_id = match_pl.group(1)
                        
                        # Define URL padrão de playlist do YouTube para o player reconhecer
                        yt_pl_url = f"https://www.youtube.com/playlist?list={pl_id}"
                        
                        st.session_state.preview_media = {
                            "resolved_url": yt_pl_url,
                            "media_info": {"title": label, "type": "video", "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/YouTube_full-color_icon_%282017%29.svg/256px-YouTube_full-color_icon_%282017%29.svg.png"}
                        }
                        st.session_state.video_url = yt_pl_url
                        
                        # Adiciona um item na lista para permitir reabrir caso o player seja fechado
                        st.session_state.current_url = url
                        st.session_state.current_items = [{
                            'label': f"▶️ (Re)abrir Playlist: {label}",
                            'url': url,
                            'isFolder': False,
                            'art': {'icon': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/YouTube_full-color_icon_%282017%29.svg/256px-YouTube_full-color_icon_%282017%29.svg.png'}
                        }]
                        return
            # -------------------------------------------
            
            # Procura em addons instalados ou pasta de desenvolvimento
            plugin_path = os.path.join(ADDONS_DIR, plugin_id)
            if not os.path.exists(plugin_path):
                plugin_path = os.path.join(PLUGINS_REPO_DIR, plugin_id)
            
            # Verifica e instala dependências antes de executar
            install_dependencies(plugin_path)
            
            # Verifica se é um Repositório (prioridade para navegação se for repo)
            addon_xml = os.path.join(plugin_path, 'addon.xml')
            is_repo = False
            if os.path.exists(addon_xml):
                try:
                    tree = ET.parse(addon_xml)
                    root = tree.getroot()
                    for ext in root.findall('extension'):
                        if ext.get('point') == 'xbmc.addon.repository':
                            is_repo = True
                            break
                except:
                    pass
            
            # Se for repositório e não tivermos parâmetros específicos (navegação raiz),
            # forçamos o modo de navegação de repositório em vez de executar o script.
            if is_repo and (not "?" in url):
                entry_point = None 
            else:
                # Tenta encontrar o entry point (script principal)
                entry_point = None
                
                # 1. Tenta ler do addon.xml
                if os.path.exists(addon_xml):
                    try:
                        tree = ET.parse(addon_xml)
                        root = tree.getroot()
                        for ext in root.findall('extension'):
                            if ext.get('point') in ['xbmc.python.pluginsource', 'xbmc.python.script']:
                                lib = ext.get('library')
                                if lib:
                                    candidate = os.path.join(plugin_path, lib)
                                    if os.path.exists(candidate):
                                        entry_point = candidate
                                        break
                    except:
                        pass
                
                # 2. Fallback para nomes padrão
                if not entry_point:
                    for name in ["main.py", "default.py", "plugin.py", "addon.py"]:
                        candidate = os.path.join(plugin_path, name)
                        if os.path.exists(candidate):
                            entry_point = candidate
                            break
            
            if entry_point and os.path.exists(entry_point):
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
                    # Salva a URL que causou o diálogo para ser retomada corretamente
                    st.session_state.pending_action_url = url
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
                    r_url = result["resolved_url"]
                    
                    # Se a URL resolvida for outro comando de plugin, executa recursivamente
                    if r_url.startswith("plugin://"):
                        # Fix para links Elementum com magnet não codificado (quebra se tiver &)
                        if "plugin.video.elementum" in r_url and "uri=magnet" in r_url and "uri=magnet%3A" not in r_url:
                             try:
                                 if "?" in r_url:
                                     base, query = r_url.split('?', 1)
                                     # Tenta capturar o magnet link bruto usando Regex para não quebrar nos & internos
                                     match = re.search(r'uri=(magnet:[^&]+)', query)
                                     if match:
                                         magnet = match.group(1)
                                         encoded_magnet = urllib.parse.quote(magnet)
                                         r_url = r_url.replace(magnet, encoded_magnet)
                                         print(f"[FIX] URL Elementum corrigida: {r_url}")
                             except Exception as e:
                                 print(f"Erro ao corrigir URL Elementum: {e}")

                        # Evita loop infinito se for igual à URL atual
                        print(f"[NAV] Redirecting to plugin URL: {r_url}")

                        if r_url != url:
                            navigate_to(r_url, label, None)
                            return
                    
                    # Se for um link Magnet, tenta repassar para o Elementum
                    if r_url.startswith("magnet:"):
                        # Verifica se o Elementum está instalado
                        if os.path.exists(os.path.join(ADDONS_DIR, "plugin.video.elementum")):
                            st.toast("🧲 Redirecionando para Elementum...")
                            elementum_url = f"plugin://plugin.video.elementum/play?uri={urllib.parse.quote(r_url)}"
                            navigate_to(elementum_url, label, dialog_answers)
                            return

                    # É um vídeo para tocar
                    # Define preview e inicia reprodução direta (Autoplay)
                    st.session_state.preview_media = result
                    st.session_state.video_url = r_url
                    st.session_state.active_plugin_url = url # Salva URL original para playlist
                    # Limpa pendência
                    if 'pending_action_url' in st.session_state: del st.session_state.pending_action_url
                else:
                    # É um diretório
                    items = result.get("items", [])
                    if not items and not result.get("error"):
                         if "elementum" in url:
                             st.warning("O Elementum não retornou dados. Verifique se o serviço/binário está rodando.")
                             print(f"[NAV] Elementum returned no data for URL: {url}")
                    
                    st.session_state.current_items = items
                    st.session_state.current_url = url
                    st.session_state.video_url = None # Limpa vídeo anterior
                    st.session_state.active_plugin_url = None
                    # Limpa pendência
                    if 'pending_action_url' in st.session_state: del st.session_state.pending_action_url
            else:
                # Tenta verificar se é um Repositório (que não tem main.py)
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
                                            
                                            content = r.content
                                            # Suporte a repositórios compactados (.gz)
                                            if info_url.endswith('.gz') or content[:2] == b'\x1f\x8b':
                                                try:
                                                    with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                                                        content = gz.read()
                                                except Exception as e:
                                                    print(f"Aviso: Falha ao descompactar GZ: {e}")

                                            remote_root = ET.fromstring(content)
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
                        if "127.0.0.1" in str(e) or "localhost" in str(e):
                            st.warning(f"⚠️ Falha ao conectar ao serviço local do repositório ({plugin_id}).")
                            st.info("Este repositório requer que um serviço de fundo (daemon) esteja rodando na sua máquina para funcionar. Em ambientes web/simulados, isso geralmente não é suportado automaticamente.")
                        else:
                            st.error(f"Erro ao ler repositório: {e}")
                
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
        st.session_state.active_plugin_url = None
    st.session_state.preview_media = None
    
    print("[NAV] Going back to previous page.")