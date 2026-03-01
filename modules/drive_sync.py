import os
import shutil
import streamlit as st
import google_storage
from core.utils import PLUGINS_REPO_DIR, ADDONS_DIR

def sync_local_plugins():
    """Copia plugins da pasta 'plugin' (repo) para 'data/addons' (instalados)."""
    if not os.path.exists(PLUGINS_REPO_DIR):
        return 0
        
    if not os.path.exists(ADDONS_DIR):
        os.makedirs(ADDONS_DIR)
        
    count = 0
    for item in os.listdir(PLUGINS_REPO_DIR):
        src_path = os.path.join(PLUGINS_REPO_DIR, item)
        dst_path = os.path.join(ADDONS_DIR, item)
        
        # Verifica se é um plugin válido (tem addon.xml)
        if os.path.isdir(src_path) and os.path.exists(os.path.join(src_path, 'addon.xml')):
            # Remove versão antiga se existir para garantir atualização limpa
            if os.path.exists(dst_path):
                shutil.rmtree(dst_path)
            
            shutil.copytree(src_path, dst_path)
            count += 1
            
    return count

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

    # 3. Sincronizar plugins locais (plugin -> data/addons)
    with st.spinner("Atualizando plugins padrão locais..."):
        local_count = sync_local_plugins()

    if total_downloaded > 0:
        st.success("Sincronização concluída! Os plugins agora estão disponíveis na fonte 'Plugins Kodi'.")
        if local_count > 0:
            st.info(f"Também foram atualizados {local_count} plugins padrão locais.")
    else:
        st.warning("Nenhuma pasta de plugin ('plugin' ou 'data/addons') encontrada para sincronizar.")