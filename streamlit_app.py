import streamlit as st
import os
import sys
import xml.etree.ElementTree as ET
import urllib.parse
import google_storage
import socket

# Adiciona o diretório atual ao path para importar os módulos core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- Configuração de Bibliotecas Locais (Fallback) ---
LOCAL_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if not os.path.exists(LOCAL_LIB_DIR):
    os.makedirs(LOCAL_LIB_DIR)
if LOCAL_LIB_DIR not in sys.path:
    sys.path.insert(0, LOCAL_LIB_DIR)

from core.utils import PLUGINS_REPO_DIR, ADDONS_DIR
from modules.utils import remove_kodi_formatting
from modules.drive_sync import sync_drive_plugins, sync_local_plugins
from modules.navigation import navigate_to, go_back
from core.services import check_and_start_services

st.set_page_config(page_title="Streamlit Media Player", layout="wide")

# --- Verificação de Configuração Essencial ---
if not st.secrets:
    st.warning("⚠️ **Atenção:** Arquivo `.streamlit/secrets.toml` não encontrado ou vazio. As funcionalidades do Google Drive estarão desativadas.")

# --- Inicialização de Estado ---
if 'history' not in st.session_state:
    st.session_state.history = []  # Pilha de navegação [(url, label)]
if 'current_url' not in st.session_state:
    st.session_state.current_url = None
if 'current_items' not in st.session_state:
    st.session_state.current_items = []
if 'preview_media' not in st.session_state:
    st.session_state.preview_media = None # Armazena metadados antes do play
if 'input_dialog' not in st.session_state:
    st.session_state.input_dialog = None # Armazena estado do diálogo de texto
if 'recent_history' not in st.session_state:
    st.session_state.recent_history = [] # Histórico persistente da Home
if 'last_error' not in st.session_state:
    st.session_state.last_error = None # Armazena erro do último plugin executado
if 'dialog_heading' not in st.session_state:
    st.session_state.dialog_heading = None # Armazena título do diálogo de seleção
if 'pending_action_url' not in st.session_state:
    st.session_state.pending_action_url = None # Armazena a URL que gerou o diálogo (para retomar)
if 'adult_unlocked' not in st.session_state:
    st.session_state.adult_unlocked = False # Controle de acesso adulto
if 'password_required' not in st.session_state:
    st.session_state.password_required = False # Flag para exibir diálogo de senha
if 'active_plugin_url' not in st.session_state:
    st.session_state.active_plugin_url = None # Armazena a URL original do plugin para playlist
if 'local_sync_done' not in st.session_state:
    # Garante que plugins padrão estejam em data/addons na primeira execução
    sync_local_plugins()
    
    # --- Criação de Playlists/Atalhos de Exemplo (.strm) ---
    try:
        # Alterado para pasta 'playlists' na raiz do projeto para garantir que suba pro GitHub
        playlists_dir = os.path.join(os.getcwd(), "playlists")
        if not os.path.exists(playlists_dir):
            os.makedirs(playlists_dir)
        
        samples = {
            "LoFi Radio (YouTube).strm": "https://www.youtube.com/watch?v=jfKfPfyJRdk",
            "News Live (YouTube).strm": "https://www.youtube.com/watch?v=1nodQjMbaSs"
        }
        for name, link in samples.items():
            p = os.path.join(playlists_dir, name)
            if not os.path.exists(p):
                with open(p, "w") as f: f.write(link)
    except Exception as e:
        print(f"Erro ao criar samples .strm: {e}")

    st.session_state.local_sync_done = True
    
    # Inicia serviços em background (ex: servidor do repositório Elementum)
    check_and_start_services()


# --- Interface ---

# Layout do Cabeçalho (Navbar) com QR Code
col_header_1, col_header_2 = st.columns([6, 1])

with col_header_1:
    st.title("📺 Media Player Web")

with col_header_2:
    # --- Detecção de Endereços (Público e Local) ---
    public_url = st.secrets.get("media_player_drive", {}).get("public_url")
    
    local_ips = []
    try:
        # Método 1: Conexão externa (IP da rota padrão - mais confiável)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ips.append(s.getsockname()[0])
        s.close()
    except: pass
    
    try:
        # Método 2: Listar interfaces de rede (para pegar 192.168.x.x, 10.x.x.x, etc)
        hostname = socket.gethostname()
        _, _, ips = socket.gethostbyname_ex(hostname)
        for ip in ips:
            if ip.startswith("192.168.") or ip.startswith("10.") or (ip.startswith("172.") and 16 <= int(ip.split('.')[1]) <= 31):
                if ip not in local_ips:
                    local_ips.append(ip)
    except: pass
    
    if not local_ips:
        local_ips = ["localhost"]

    with st.popover("📱 Acessar"):
        st.markdown("### 📲 Conectar Celular")
        
        # Abas para Público vs Local
        tabs_labels = []
        if public_url: tabs_labels.append("☁️ Público")
        tabs_labels.append("🏠 Local")
        
        selected_tab = st.radio("Rede:", tabs_labels, horizontal=True, label_visibility="collapsed")
        
        target_url = ""
        
        if selected_tab == "☁️ Público":
            target_url = public_url
            st.caption("Acesso via Internet (Requer URL configurada no secrets.toml)")
        else:
            # Se houver múltiplos IPs locais, permite escolher
            if len(local_ips) > 1:
                selected_ip = st.selectbox("Selecione o IP:", local_ips)
            else:
                selected_ip = local_ips[0]
            
            target_url = f"http://{selected_ip}:8501"
            st.caption("Acesso via Wi-Fi (Mesma rede)")

        if target_url:
            # Gera QR Code
            encoded_url = urllib.parse.quote(target_url)
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={encoded_url}"
            st.image(qr_url, width=250)
            st.code(target_url, language="text")
        
        st.divider()
        st.warning("🚫 **Não conecta?**\n\n1. Verifique se o celular está no **mesmo Wi-Fi**.\n2. O **Firewall do Windows** pode estar bloqueando. Tente desativá-lo temporariamente para testar.")

# --- Diálogo de Senha (Conteúdo Adulto) ---
if st.session_state.password_required:
    with st.container(border=True):
        st.warning("🔒 Conteúdo Protegido")
        st.write("Este plugin contém material adulto. Digite a senha para continuar.")
        with st.form(key='password_form'):
            password = st.text_input("Senha:", type="password")
            c1, c2 = st.columns([1, 5])
            with c1:
                submit = st.form_submit_button("Desbloquear", type="primary", use_container_width=True)
            
            if submit:
                # Senha padrão: 6969 (pode ser alterada no secrets.toml com 'adult_password = "..."')
                correct_pass = st.secrets.get("adult_password", "6969")
                if password == str(correct_pass):
                    st.session_state.adult_unlocked = True
                    st.session_state.password_required = False
                    # Retoma a navegação
                    url = st.session_state.get('pending_password_url')
                    label = st.session_state.get('pending_password_label')
                    if url:
                        navigate_to(url, label)
                    st.rerun()
                else:
                    st.error("Senha incorreta.")
    st.stop()

# --- Diálogo de Input (Teclado Virtual) ---
if st.session_state.input_dialog:
    with st.container(border=True):
        st.info(f"⌨️ {st.session_state.input_dialog['heading']}")
        with st.form(key='input_form'):
            user_text = st.text_input("Digite sua busca:", value=st.session_state.input_dialog['default'])
            col_sub_1, col_sub_2 = st.columns([1, 5])
            with col_sub_1:
                submitted = st.form_submit_button("Enviar", type="primary", use_container_width=True)
            
            if submitted:
                url = st.session_state.input_dialog_url
                st.session_state.input_dialog = None
                # Retoma a navegação passando a resposta do usuário
                navigate_to(url, "Resultado da Busca", dialog_answers=[user_text])
                st.rerun()
    st.stop() # Para a renderização do resto da página até o usuário responder

# Sidebar: Lista de Plugins Instalados
with st.sidebar:
    st.header("Fonte de Mídia")
    source_mode = st.radio("Escolha a origem:", ["Plugins Kodi", "Google Drive", "Arquivos Locais"])
    
    # Botão Global de Parar (Útil quando o player está tocando rádio de fundo)
    if st.session_state.get('video_url'):
        if st.button("⏹️ Parar Reprodução", use_container_width=True, type="primary"):
            st.session_state.video_url = None
            st.rerun()
    
    if source_mode == "Plugins Kodi":
        plugins_by_category = {}
        
        # Escaneia pastas
        for d in [ADDONS_DIR, PLUGINS_REPO_DIR]:
            if os.path.exists(d):
                for item in os.listdir(d):
                    plugin_path = os.path.join(d, item)
                    addon_xml = os.path.join(plugin_path, 'addon.xml')
                    
                    if os.path.isdir(plugin_path) and os.path.exists(addon_xml):
                        # Tenta extrair nome do XML
                        name = item
                        try:
                            tree = ET.parse(addon_xml)
                            root = tree.getroot()
                            name = root.get('name', item)
                        except:
                            pass
                        name = remove_kodi_formatting(name)
                        
                        # Categoriza pelo ID
                        category = "Outros"
                        if item.startswith("plugin.video"):
                            category = "Vídeo"
                        elif item.startswith("plugin.audio"):
                            category = "Áudio"
                        elif item.startswith("plugin.program"):
                            category = "Programas"
                        elif item.startswith("repository"):
                            category = "Repositórios"
                        elif item.startswith("script"):
                            category = "Scripts"
                            
                        if category not in plugins_by_category:
                            plugins_by_category[category] = []
                        
                        # Evita duplicatas
                        if not any(p['id'] == item for p in plugins_by_category[category]):
                            plugins_by_category[category].append({'id': item, 'name': name})

        # Ordena categorias
        categories = sorted(plugins_by_category.keys())
        
        if not categories:
            st.warning("Nenhum plugin encontrado.")
        else:
            # Seleção de Categoria
            selected_category = st.selectbox("Categoria", ["Selecione..."] + categories)
            
            if selected_category != "Selecione...":
                # Lista de plugins da categoria
                cat_plugins = plugins_by_category[selected_category]
                # Cria labels para o selectbox: "Nome (ID)"
                plugin_options = {f"{p['name']} ({p['id']})": p['id'] for p in cat_plugins}
                
                selected_label = st.selectbox("Plugin", ["Selecione..."] + list(plugin_options.keys()))
                
                if st.button("Carregar Plugin"):
                    if selected_label != "Selecione...":
                        # Reseta o player e preview ao trocar de plugin
                        st.session_state.video_url = None
                        st.session_state.preview_media = None
                        
                        selected_id = plugin_options[selected_label]
                        selected_name = next((p['name'] for p in cat_plugins if p['id'] == selected_id), selected_id)
                        start_url = f"plugin://{selected_id}/"
                        st.session_state.history = [(start_url, selected_name)]
                        navigate_to(start_url, selected_name)

    elif source_mode == "Google Drive":
        if st.button("📂 Carregar Drive"):
            # Inicia navegação pela raiz
            start_url = "gdrive_folder://root"
            st.session_state.history = [(start_url, "Google Drive")]
            navigate_to(start_url, "Google Drive")
            st.rerun()
        
        st.markdown("---")
        with st.expander("⚙️ Sincronizar Plugins do Drive"):
            st.info("Isso irá baixar os plugins das pastas 'plugin' e 'data/addons' do seu Drive para o player local.")
            if st.button("Iniciar Sincronização"):
                sync_drive_plugins()
        
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
                # Detecta se estamos navegando no Drive ou Local
                is_gdrive = st.session_state.current_url and st.session_state.current_url.startswith("gdrive")
                
                btn_label = "Enviar para Google Drive" if is_gdrive else "Salvar no Servidor (Temporário)"
                
                if st.button(btn_label):
                    if is_gdrive:
                        # Determina a pasta de destino baseada na navegação atual
                        target_folder = None
                        if st.session_state.current_url.startswith("gdrive_folder://"):
                            target_folder = st.session_state.current_url.replace("gdrive_folder://", "")
                            if target_folder == "root": target_folder = None

                        with st.spinner("Enviando para o Google Drive..."):
                            fid = google_storage.upload_file(uploaded_file, uploaded_file.name, folder_id=target_folder)
                            if fid:
                                st.success("Upload concluído com sucesso!")
                            else:
                                st.error("Falha no envio.")
                    else:
                        # Salva localmente em data/uploads
                        save_dir = os.path.join(os.getcwd(), "data", "uploads")
                        if not os.path.exists(save_dir):
                            os.makedirs(save_dir)
                        
                        file_path = os.path.join(save_dir, uploaded_file.name)
                        try:
                            with open(file_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())
                            st.success(f"Salvo em: {file_path}")
                            st.info("Navegue até a pasta 'data/uploads' pelo Explorador Local para reproduzir.")
                            st.warning("⚠️ Atenção: Arquivos no servidor são apagados ao reiniciar o app.")
                        except Exception as e:
                            st.error(f"Erro ao salvar: {e}")
        
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
        label = remove_kodi_formatting(label)
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
        url = st.session_state.video_url
        
        # --- Resolve arquivos .strm locais (Links de texto) ---
        if not url.startswith("http") and url.lower().endswith(".strm") and os.path.exists(url):
            try:
                with open(url, "r") as f:
                    content = f.read().strip()
                    if content: url = content
            except: pass

        # Identifica o tipo de conteúdo para separar a lógica
        is_local = not url.startswith("http")
        is_gdrive = "drive.google.com" in url
        is_stream = not is_local and not is_gdrive
        
        if is_stream:
            # ==================================================
            # CAMINHO 1: PLAYER DE STREAM (PLUGINS / IPTV)
            # ==================================================
            with st.container(border=True):
                # 1. Metadados
                display_title = "Reproduzindo Stream"
                icon = "📡"
                media_type = 'video'
                
                if st.session_state.get('preview_media'):
                    info = st.session_state.preview_media.get('media_info', {})
                    if info.get('title'):
                        display_title = remove_kodi_formatting(info['title'])
                        if info.get('artist'):
                            display_title = f"{remove_kodi_formatting(info['artist'])} - {display_title}"
                    media_type = info.get('type', 'video')
                    if media_type == 'music': icon = "🎵"
                
                st.subheader(f"{icon} {display_title}")
                
                # 2. Tratamento de URL (Headers e Redirects)
                final_url_for_player = url
                headers_for_player = ""
                clean_url = url
                
                if "|" in url:
                    clean_url = url.split("|")[0]
                    headers_str = url.split("|")[1]
                    final_url_for_player = clean_url
                    headers_for_player = headers_str
                    
                    # Resolução de Redirects (Blogger/Google)
                    try:
                        headers = {}
                        for h in headers_str.split('&'):
                            if '=' in h:
                                k, v = h.split('=', 1)
                                headers[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
                        
                        if headers:
                            import requests
                            import urllib3
                            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                            r = requests.get(clean_url, headers=headers, allow_redirects=False, stream=True, timeout=5, verify=False)
                            if r.status_code in [301, 302, 303, 307, 308] and 'Location' in r.headers:
                                clean_url = r.headers['Location']
                    except Exception as e:
                        print(f"Falha ao resolver URL protegida: {e}")

                    with st.expander("⚠️ Informações de Proteção (Headers)", expanded=False):
                        st.warning("Este vídeo usa proteção por headers. Se não tocar, é porque o navegador bloqueia requisições customizadas.")
                        st.code(headers_str)
                    
                    url = clean_url

                # --- Diagnóstico de Link (MixDrop e Status) ---
                if not url.startswith("magnet:") and "youtube.com" not in url:
                    # Aviso MixDrop/MxContent
                    if any(x in url for x in ["mixdrop", "mxcontent"]):
                         st.warning("⚠️ **MixDrop Detectado:** Este servidor frequentemente bloqueia players web. Se falhar, use o 'Player Externo'.")

                    # Verifica se o link está acessível
                    try:
                        import requests
                        # Timeout curto para não travar a UI
                        r_check = requests.head(url, timeout=2, verify=False)
                        if r_check.status_code >= 400:
                             r_check = requests.get(url, stream=True, timeout=2, verify=False)
                             r_check.close()
                        
                        if r_check.status_code >= 400:
                            st.error(f"⚠️ **Link Quebrado ou Bloqueado** (Erro {r_check.status_code})")
                            st.caption(f"O servidor retornou erro. Tente recarregar o plugin ou usar o player externo.")
                    except Exception as e:
                        print(f"Erro ao verificar link: {e}")

                # --- Lógica de Playlist para Streams (Plugins) ---
                st.session_state.current_playlist = []
                st.session_state.current_playlist_index = -1
                
                # Tenta criar playlist a partir dos itens da pasta atual (vindo de um plugin)
                if st.session_state.get('current_items'):
                    # Filtra apenas itens que não são pastas
                    playlist_items = [item for item in st.session_state.current_items if not item.get('isFolder')]
                    
                    if playlist_items:
                        st.session_state.current_playlist = playlist_items
                        
                        # Encontra o índice do item atual na playlist
                        # Compara URLs sem os headers para garantir o match
                        current_url_no_headers = url.split('|')[0]
                        
                        # Tenta usar a URL original do plugin se disponível (para casos onde video_url é resolvido)
                        target_url = st.session_state.get('active_plugin_url', current_url_no_headers)
                        
                        for i, item in enumerate(playlist_items):
                            item_url_no_headers = item['url'].split('|')[0]
                            if item_url_no_headers == target_url or item_url_no_headers == current_url_no_headers:
                                st.session_state.current_playlist_index = i
                                break

                # 3. Player
                if url.startswith("magnet:"):
                    st.warning("🧲 Links Magnet (Torrent) não são suportados nativamente pelo navegador.")
                    st.info("O plugin retornou um link magnético em vez de um stream de vídeo. Isso pode indicar que o motor de torrent (Elementum/TorrServer) não iniciou corretamente.")
                    st.code(url, language="text")
                elif "youtube.com/playlist" in url:
                    # Player Embed para Playlists do YouTube
                    try:
                        pl_id = url.split("list=")[-1].split("&")[0]
                        iframe_html = f'<iframe width="100%" height="480" src="https://www.youtube.com/embed/videoseries?list={pl_id}" frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>'
                        st.markdown(iframe_html, unsafe_allow_html=True)
                    except:
                        st.error("Erro ao carregar playlist.")
                elif media_type == 'music':
                    st.audio(url, autoplay=True)
                else:
                    st.video(url, autoplay=True)
                
                # --- Botões de Navegação da Playlist (Stream) ---
                if st.session_state.get('current_playlist') and st.session_state.current_playlist_index != -1:
                    idx = st.session_state.current_playlist_index
                    total = len(st.session_state.current_playlist)
                    
                    st.caption(f"Na playlist: {idx + 1} de {total}")
                    
                    col_prev, col_next = st.columns(2)
                    
                    with col_prev:
                        if st.button("⏮️ Anterior", use_container_width=True, disabled=(idx <= 0)):
                            next_item = st.session_state.current_playlist[idx - 1]
                            # Usa navigate_to para resolver plugins corretamente
                            navigate_to(next_item['url'], next_item['label'])
                            st.rerun()
                    
                    with col_next:
                        if st.button("Próxima ⏭️", use_container_width=True, disabled=(idx >= total - 1)):
                            next_item = st.session_state.current_playlist[idx + 1]
                            # Usa navigate_to para resolver plugins corretamente
                            navigate_to(next_item['url'], next_item['label'])
                            st.rerun()

                # 4. Diagnóstico de Mixed Content
                is_https_env = "https://" in (st.secrets.get("media_player_drive", {}).get("public_url") or "") or "streamlit.app" in (st.secrets.get("media_player_drive", {}).get("public_url") or "")
                if url.startswith("http://") and is_https_env:
                    st.warning("⚠️ **Bloqueio de Conteúdo Misto (Mixed Content)**")
                    st.caption("O vídeo é **HTTP** (inseguro) mas o site é **HTTPS**. O navegador bloqueou a reprodução.")
                    st.markdown("👉 **Solução:** Use o link abaixo no VLC ou permita 'Conteúdo Inseguro' nas configurações do site no navegador.")

                # 5. Link Externo
                # Expande automaticamente se for um link problemático (MixDrop) ou tiver headers (que o navegador ignora)
                auto_expand = "mixdrop" in final_url_for_player or "mxcontent" in final_url_for_player or bool(headers_for_player)
                
                with st.expander("📺 Player Externo / Link Direto", expanded=auto_expand):
                    st.write("Se não tocar no navegador, copie o link abaixo e use no **VLC**, **MPV** ou **PotPlayer**.")
                    if headers_for_player:
                        st.code(f'{final_url_for_player}|{headers_for_player}', language="text")
                    else:
                        st.code(final_url_for_player, language="text")

                # 6. Controles e QR Code
                if st.button("⏹️ Parar Reprodução", use_container_width=True, key="stop_stream"):
                    st.session_state.video_url = None
                    st.rerun()
                    
                with st.expander("📱 Assistir no Celular"):
                    qr_target = url
                    if "|" in qr_target: qr_target = qr_target.split("|")[0]
                    encoded_url = urllib.parse.quote(qr_target)
                    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_url}"
                    c1, c2 = st.columns([1, 3])
                    c1.image(qr_api, width=150)
                    c2.info("Escaneie para abrir o vídeo no celular.")
                    c2.code(qr_target, language="text")

        else:
            # ==================================================
            # CAMINHO 2: PLAYER DE ARQUIVO (LOCAL / DRIVE)
            # ==================================================
            with st.container(border=True):
                # 1. Metadados
                display_title = "Reproduzindo Arquivo"
                icon = "📂"
                if is_gdrive: icon = "☁️"
                media_type = 'video'

                if st.session_state.get('preview_media'):
                    info = st.session_state.preview_media.get('media_info', {})
                    if info.get('title'):
                        display_title = remove_kodi_formatting(info['title'])
                    media_type = info.get('type', 'video')
                    if media_type == 'music': icon = "🎵"
                
                st.subheader(f"{icon} {display_title}")
                
                # --- Lógica de Playlist para Arquivos Locais ---
                st.session_state.current_playlist = []
                st.session_state.current_playlist_index = -1

                if is_local:
                    try:
                        current_file_path = urllib.parse.unquote(url)
                        directory = os.path.dirname(current_file_path)
                        
                        # Lista todos os arquivos de mídia suportados na pasta
                        media_files = sorted([
                            f for f in os.listdir(directory) 
                            if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.strm'))
                        ])
                        
                        st.session_state.current_playlist = [os.path.join(directory, f) for f in media_files]
                        
                        # Encontra o índice do arquivo atual
                        if current_file_path in st.session_state.current_playlist:
                            st.session_state.current_playlist_index = st.session_state.current_playlist.index(current_file_path)
                    except Exception as e:
                        print(f"Erro ao criar playlist local: {e}")

                # 2. Player
                if is_local and not os.path.exists(url):
                    st.error(f"Arquivo local não encontrado: {url}")
                elif media_type == 'music':
                    st.audio(url, autoplay=True)
                else:
                    st.video(url, autoplay=True)
                
                # --- Botões de Navegação da Playlist ---
                if st.session_state.get('current_playlist') and st.session_state.current_playlist_index != -1:
                    idx = st.session_state.current_playlist_index
                    total = len(st.session_state.current_playlist)
                    
                    st.caption(f"Na playlist: {idx + 1} de {total}")
                    
                    col_prev, col_next = st.columns(2)
                    
                    with col_prev:
                        # Botão Anterior (desabilitado se for o primeiro)
                        if st.button("⏮️ Anterior", use_container_width=True, disabled=(idx <= 0)):
                            next_url = st.session_state.current_playlist[idx - 1]
                            st.session_state.video_url = next_url
                            if st.session_state.preview_media:
                                st.session_state.preview_media['resolved_url'] = next_url
                                st.session_state.preview_media['media_info']['title'] = os.path.basename(next_url)
                            st.rerun()
                    
                    with col_next:
                        # Botão Próximo (desabilitado se for o último)
                        if st.button("Próxima ⏭️", use_container_width=True, disabled=(idx >= total - 1)):
                            next_url = st.session_state.current_playlist[idx + 1]
                            st.session_state.video_url = next_url
                            if st.session_state.preview_media:
                                st.session_state.preview_media['resolved_url'] = next_url
                                st.session_state.preview_media['media_info']['title'] = os.path.basename(next_url)
                            st.rerun()

                # 3. Fallbacks do Drive
                if is_gdrive:
                    with st.expander("🆘 O vídeo não toca? (Opções do Drive)", expanded=False):
                        st.info("1. Para o player acima funcionar, o arquivo deve estar como **'Qualquer pessoa com o link'**.")
                        st.info("2. Arquivos **MKV/AVI** não tocam no player padrão. Use o Player Nativo abaixo:")
                        
                        if "id=" in url:
                            f_id = url.split("id=")[-1].split("&")[0]
                            st.markdown(f"### 📽️ Player Nativo (Transcodificado)")
                            iframe_html = f'<iframe src="https://drive.google.com/file/d/{f_id}/preview" width="100%" height="480" style="border:none; border-radius:10px;" allow="autoplay; fullscreen"></iframe>'
                            st.markdown(iframe_html, unsafe_allow_html=True)

                # 4. Controles e QR Code
                if st.button("⏹️ Parar Reprodução", use_container_width=True, key="stop_file"):
                    st.session_state.video_url = None
                    st.rerun()
                
                if not is_local:
                    with st.expander("📱 Assistir no Celular"):
                        encoded_url = urllib.parse.quote(url)
                        qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_url}"
                        c1, c2 = st.columns([1, 3])
                        c1.image(qr_api, width=150)
                        c2.info("Escaneie para abrir o vídeo no celular.")
                        c2.code(url, language="text")
                else:
                    st.info("ℹ️ Arquivo local. QR Code indisponível.")

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
                title = remove_kodi_formatting(info.get('title', 'Pronto para reproduzir'))
                media_type = info.get('type', 'video')
                
                icon = "🎬" # default video
                if media_type == 'music':
                    icon = "🎵"
                elif media_type == 'picture':
                    icon = "🖼️"
                
                st.markdown(f"### {icon} {title}")
                
                if info.get('artist'):
                    st.write(f"**Artista:** {remove_kodi_formatting(info['artist'])}")
                if info.get('plot'):
                    st.caption(remove_kodi_formatting(info['plot']))
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
    items = st.session_state.current_items
    # Fecha a lista se estiver vendo vídeo ou preview para focar no conteúdo
    is_viewing_content = (st.session_state.get('video_url') is not None) or (st.session_state.get('preview_media') is not None)

    # --- MENSAGENS PERSISTENTES (Fora do Expander) ---
    if st.session_state.last_error:
        st.error(f"❌ Erro no Plugin: {st.session_state.last_error}")
        
    if st.session_state.dialog_heading:
        st.info(f"👉 Selecione: **{st.session_state.dialog_heading}**")
    
    with st.expander("📂 Navegador de Arquivos", expanded=not is_viewing_content):
            
        if not items:
            if st.session_state.dialog_heading:
                st.warning("⚠️ O plugin abriu um menu de seleção vazio. Isso geralmente indica que ele não conseguiu encontrar opções (ex: links ou idiomas) no site de origem.")
            # Se a URL atual existe, a pasta está realmente vazia.
            elif st.session_state.current_url:
                    st.info(f"Esta pasta está vazia.\nURL: {st.session_state.current_url}")
            # Se não há URL, significa que a navegação inicial falhou.
            else:
                st.error("Ocorreu um erro ao tentar carregar o conteúdo.")
                st.warning("Isso pode acontecer se o plugin falhou ao iniciar ou se houve um problema de conexão. Tente carregar novamente ou escolha outra fonte.")
        
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
            clean_text = remove_kodi_formatting(label)
            if col2.button(clean_text, key=f"btn_{idx}", use_container_width=True):
                # --- Verifica se o item é uma pasta ou um arquivo para tocar ---
                if not item.get('isFolder'):
                    # Se for um plugin, tratamos como navegação para permitir resolução ou ações
                    if item['url'].startswith("plugin://") or item['url'].startswith("resume:") or item['url'].startswith("install://"):
                        if not item['url'].startswith("resume:") and not item['url'].startswith("install://"):
                            st.session_state.history.append((item['url'], clean_text))
                        navigate_to(item['url'], clean_text)
                    else:
                        # --- ARQUIVO/STREAM DIRETO ---
                        # Extrai os metadados do 'listitem' que a ponte do Kodi nos envia
                        listitem = item.get('listitem')
                        media_info = {}
                        
                        if listitem:
                            info = getattr(listitem, 'info', {}).copy()
                            art = getattr(listitem, 'art', {}).copy()
                            item_type = getattr(listitem, 'media_type', 'video')
                            
                            if 'title' not in info:
                                info['title'] = listitem.getLabel()
                            
                            media_info = {
                                "title": info.get('title'),
                                "artist": info.get('artist'),
                                "plot": info.get('plot'),
                                "icon": art.get('icon') or art.get('thumb'),
                                "type": item_type
                            }
                        else:
                            media_info = {"title": clean_text, "type": "video"}

                        # Define o estado de pré-visualização para mostrar a tela de "play"
                        st.session_state.preview_media = {
                            "resolved_url": item['url'],
                            "media_info": media_info
                        }
                        st.session_state.video_url = item['url']
                else:
                    # --- PASTA ---
                    new_url = item['url']
                    if not new_url.startswith("resume:"):
                        st.session_state.history.append((new_url, clean_text))
                    navigate_to(new_url, clean_text)
                st.rerun()
else:
    # --- PÁGINA INICIAL (DASHBOARD) ---
    st.markdown("## 🏠 Início")
    
    # Seção 1: Acesso Rápido
    st.subheader("🚀 Acesso Rápido")
    c1, c2, c3 = st.columns(3)
    
    with c1:
        if st.button("📂 Google Drive", use_container_width=True):
            start_url = "gdrive_folder://root"
            st.session_state.history = [(start_url, "Google Drive")]
            navigate_to(start_url, "Google Drive")
            st.rerun()
            
    with c2:
        if st.button("💻 Arquivos Locais", use_container_width=True):
            local_explorer_id = "plugin.video.local_explorer"
            if os.path.exists(os.path.join(ADDONS_DIR, local_explorer_id)) or \
               os.path.exists(os.path.join(PLUGINS_REPO_DIR, local_explorer_id)):
                start_url = f"plugin://{local_explorer_id}/"
                st.session_state.history = [(start_url, "Arquivos Locais")]
                navigate_to(start_url, "Arquivos Locais")
                st.rerun()
            else:
                st.toast("Plugin Local Explorer não encontrado.", icon="⚠️")

    with c3:
        if st.button("⚙️ Sincronizar Plugins", use_container_width=True):
            sync_drive_plugins()

    # Seção 2: Histórico Recente
    if st.session_state.get('recent_history'):
        st.subheader("🕒 Recentes")
        for item in st.session_state.recent_history[:5]:
            if st.button(f"📄 {item['label']}", key=f"hist_{item['url']}", use_container_width=True):
                st.session_state.history = [(item['url'], item['label'])]
                navigate_to(item['url'], item['label'])
                st.rerun()

    # Seção 3: Plugins Instalados (Grid)
    st.subheader("🧩 Meus Plugins")
    found_plugins = []
    for d in [ADDONS_DIR, PLUGINS_REPO_DIR]:
        if os.path.exists(d):
            for item in os.listdir(d):
                plugin_path = os.path.join(d, item)
                addon_xml = os.path.join(plugin_path, 'addon.xml')
                if os.path.isdir(plugin_path) and os.path.exists(addon_xml):
                    name = item
                    try:
                        tree = ET.parse(addon_xml)
                        name = tree.getroot().get('name', item)
                    except: pass
                    name = remove_kodi_formatting(name)
                    if item.startswith("plugin.video") or item.startswith("plugin.audio"):
                        if not any(p['id'] == item for p in found_plugins):
                            found_plugins.append({'id': item, 'name': name})
    
    if found_plugins:
        cols = st.columns(3)
        for i, plugin in enumerate(found_plugins):
            col = cols[i % 3]
            with col:
                if st.button(plugin['name'], key=f"home_plugin_{plugin['id']}", use_container_width=True):
                    start_url = f"plugin://{plugin['id']}/"
                    st.session_state.history = [(start_url, plugin['name'])]
                    navigate_to(start_url, plugin['name'])
                    st.rerun()
    else:
        st.info("Nenhum plugin de mídia encontrado.")