import streamlit as st
import os
import sys
import subprocess
import importlib.util
import xml.etree.ElementTree as ET
import urllib.parse
import google_storage
import socket
import re

# Adiciona o diretório atual ao path para importar os módulos core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- Configuração de Bibliotecas Locais (Fallback) ---
LOCAL_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if not os.path.exists(LOCAL_LIB_DIR):
    os.makedirs(LOCAL_LIB_DIR)
if LOCAL_LIB_DIR not in sys.path:
    sys.path.insert(0, LOCAL_LIB_DIR)

from core.kodi_bridge import run_plugin
from core.utils import PLUGINS_REPO_DIR, ADDONS_DIR

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

# --- Funções Auxiliares ---

def remove_kodi_formatting(text):
    """Remove tags de formatação do Kodi ([B], [COLOR], etc)."""
    if not text: return ""
    # Remove tags como [B], [/B], [COLOR red], [CR], etc.
    return re.sub(r'\[/?[A-Z]+(?: [^\]]+)?\]', '', text, flags=re.IGNORECASE)

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
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "--target", LOCAL_LIB_DIR] + packages_to_install)
                        importlib.invalidate_caches()
                        st.toast(f"Dependências instaladas localmente!", icon="✅")
                    except subprocess.CalledProcessError:
                        st.warning(f"Não foi possível instalar algumas dependências automaticamente: {packages_to_install}")
            
    except Exception as e:
        print(f"Erro ao verificar dependências: {e}")

def navigate_to(url, label="Home", dialog_answers=None):
    """Executa o plugin e atualiza o estado com os novos itens."""
    
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
                result = run_plugin(entry_point, params, dialog_answers=dialog_answers)
                
                if result.get("dialog_heading"):
                    # O plugin pediu uma seleção (ex: escolher servidor)
                    st.session_state.current_items = result["items"]
                    # Não limpamos current_url para permitir o resume na mesma URL
                    st.session_state.video_url = None
                    st.toast(f"Selecione: {result['dialog_heading']}")
                    return

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

def sync_drive_plugins():
    """Encontra e baixa as pastas de plugins do Google Drive."""
    with st.spinner("Conectando ao Google Drive..."):
        service = google_storage.get_drive_service()
        root_id = google_storage.get_folder_id()
        if not service or not root_id:
            st.error("Falha na conexão com o Google Drive. Verifique as configurações.")
            return

    total_downloaded = 0
    
    # 1. Sincronizar pasta 'plugin'
    with st.spinner("Procurando pasta 'plugin' no Drive..."):
        plugin_folder_id = google_storage.find_folder_id(service, root_id, 'plugin')
    
    if plugin_folder_id:
        with st.spinner("Sincronizando plugins de desenvolvimento..."):
            if not os.path.exists(PLUGINS_REPO_DIR):
                os.makedirs(PLUGINS_REPO_DIR)
            count = google_storage.download_folder_recursively(service, plugin_folder_id, PLUGINS_REPO_DIR)
            total_downloaded += count
            st.toast(f"{count} itens sincronizados da pasta 'plugin'.")
    else:
        st.info("Pasta 'plugin' não encontrada na raiz do Drive.")

    # 2. Sincronizar pasta 'data/addons'
    with st.spinner("Procurando pasta 'data' no Drive..."):
        data_folder_id = google_storage.find_folder_id(service, root_id, 'data')
        addons_folder_id = None
        if data_folder_id:
            with st.spinner("Procurando pasta 'addons' dentro de 'data'..."):
                addons_folder_id = google_storage.find_folder_id(service, data_folder_id, 'addons')

    if addons_folder_id:
        with st.spinner("Sincronizando addons instalados..."):
            if not os.path.exists(ADDONS_DIR):
                os.makedirs(ADDONS_DIR)
            count = google_storage.download_folder_recursively(service, addons_folder_id, ADDONS_DIR)
            total_downloaded += count
            st.toast(f"{count} itens sincronizados de 'data/addons'.")
    else:
        st.info("Pasta 'data/addons' não encontrada no Drive.")

    if total_downloaded > 0:
        st.success("Sincronização concluída! Os plugins agora estão disponíveis na fonte 'Plugins Kodi'.")
    else:
        st.warning("Nenhuma pasta de plugin ('plugin' ou 'data/addons') encontrada para sincronizar.")

# --- Interface ---

# Layout do Cabeçalho (Navbar) com QR Code
col_header_1, col_header_2 = st.columns([6, 1])

with col_header_1:
    st.title("📺 Media Player Web")

with col_header_2:
    # --- Lógica para obter a URL correta (Cloud vs. Local) ---
    # 1. Tenta obter a URL pública configurada nos secrets (para deploy na nuvem)
    app_url = st.secrets.get("media_player_drive", {}).get("public_url")
    url_source = ""

    if app_url:
        url_source = "URL pública (secrets.toml)"
    else:
        # 2. Se não, tenta obter o IP local manual configurado nos secrets
        local_ip_manual = st.secrets.get("media_player_drive", {}).get("local_ip")
        if local_ip_manual:
            app_url = f"http://{local_ip_manual}:8501"
            url_source = "IP local manual (secrets.toml)"
        else:
            # 3. Se não houver URL pública nem IP manual, tenta descobrir o IP local (para uso em rede Wi-Fi)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                app_url = f"http://{local_ip}:8501"
                url_source = "IP local (detecção automática)"
            except:
                app_url = "http://localhost:8501" # Fallback final
                url_source = "localhost (fallback)"

    # Imprime no console a URL que realmente está sendo usada (para debug)
    print(f"🔗 URL DE ACESSO (QR CODE): {app_url} (Fonte: {url_source})")

    with st.popover("📱 Acessar"):
        st.markdown("### 📲 Conectar Celular")
        
        # Permite edição manual do IP na interface para correção imediata
        current_host = app_url.split("://")[-1].split(":")[0]
        manual_host = st.text_input("IP da Máquina:", value=current_host, help="Se o QR Code estiver errado, digite o IP correto aqui (ex: 192.168.0.15).")
        
        final_url = f"http://{manual_host}:8501"
        
        qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(final_url)}"
        st.image(qr_code_url, width=200)
        st.code(final_url, language="text")
        
        st.divider()
        st.warning("🚫 **Não conecta?**\n\n1. Verifique se o celular está no **mesmo Wi-Fi**.\n2. O **Firewall do Windows** pode estar bloqueando. Tente desativá-lo temporariamente para testar.")

# Sidebar: Lista de Plugins Instalados
with st.sidebar:
    st.header("Fonte de Mídia")
    source_mode = st.radio("Escolha a origem:", ["Plugins Kodi", "Google Drive", "Arquivos Locais"])
    
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
                        selected_id = plugin_options[selected_label]
                        selected_name = next((p['name'] for p in cat_plugins if p['id'] == selected_id), selected_id)
                        start_url = f"plugin://{selected_id}/"
                        st.session_state.history = [(start_url, selected_name)]
                        navigate_to(start_url)

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
    with st.container(border=True):
        # Tenta obter título dos metadados salvos
        display_title = "Reproduzindo Agora"
        icon = "🍿"
        media_type = 'video' # Padrão
        if st.session_state.get('preview_media'):
            info = st.session_state.preview_media.get('media_info', {})
            if info.get('title'):
                display_title = remove_kodi_formatting(info['title'])
                if info.get('artist'):
                    display_title = f"{remove_kodi_formatting(info['artist'])} - {display_title}"
            
            media_type = info.get('type', 'video') # Pega o tipo de mídia
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

        # Usa o player correto para cada tipo de mídia
        if media_type == 'music':
            st.audio(url, autoplay=True)
        else:
            st.video(url, autoplay=True)
        
        # Se for link do Google Drive, oferece opções de fallback (Iframe e Aviso de Permissão)
        if "drive.google.com" in url:
            with st.expander("🆘 O vídeo não toca? (Opções do Drive)", expanded=False):
                st.info("1. Para o player acima funcionar, o arquivo deve estar como **'Qualquer pessoa com o link'**.")
                st.info("2. Arquivos **MKV/AVI** não tocam no player padrão. Use o Player Nativo abaixo:")
                
                if "id=" in url:
                    f_id = url.split("id=")[-1].split("&")[0]
                    st.markdown(f"### 📽️ Player Nativo (Transcodificado)")
                    iframe_html = f'<iframe src="https://drive.google.com/file/d/{f_id}/preview" width="100%" height="480" style="border:none; border-radius:10px;" allow="autoplay; fullscreen"></iframe>'
                    st.markdown(iframe_html, unsafe_allow_html=True)
        
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
if st.session_state.history:
    items = st.session_state.current_items
    # Fecha a lista se estiver vendo vídeo ou preview para focar no conteúdo
    is_viewing_content = (st.session_state.get('video_url') is not None) or (st.session_state.get('preview_media') is not None)
    
    with st.expander("📂 Navegador de Arquivos", expanded=not is_viewing_content):
        if not items:
            # Se a URL atual existe, a pasta está realmente vazia.
            if st.session_state.current_url:
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
                    # --- ARQUIVO/STREAM PARA TOCAR ---
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
                    st.session_state.video_url = None
                else:
                    # --- PASTA ---
                    new_url = item['url']
                    if not new_url.startswith("resume:"):
                        st.session_state.history.append((new_url, clean_text))
                    navigate_to(new_url, clean_text)
                st.rerun()
else:
    st.info("👈 Selecione um plugin na barra lateral para começar.")