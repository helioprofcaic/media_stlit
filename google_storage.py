import streamlit as st
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.http import MediaIoBaseDownload

# Escopos necessários para ler e escrever no Drive
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """Autentica e retorna o serviço do Google Drive usando st.secrets."""
    if "gcp_service_account" not in st.secrets:
        st.warning("⚠️ Credenciais do Google Cloud não configuradas nos Secrets.")
        return None
    
    try:
        # Converte o objeto de configuração do Streamlit para dict
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # --- CORREÇÃO DE FORMATAÇÃO DA CHAVE PRIVADA ---
        if "private_key" in creds_dict:
            # 1. Verifica se o usuário esqueceu de substituir o placeholder "..." do exemplo
            if "..." in creds_dict["private_key"]:
                st.error("⚠️ Erro de Configuração: A chave privada contém '...'. Você esqueceu de substituir o valor de exemplo no arquivo secrets.toml pela sua chave real.")
                return None
            # 2. Substitui literais \n por quebras de linha reais (necessário para TOML/Streamlit)
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Erro na autenticação do Google Drive: {e}")
        return None

def get_folder_id():
    """Retorna o ID da pasta do player configurado nos secrets."""
    if "media_player_drive" in st.secrets and "folder_id" in st.secrets["media_player_drive"]:
        return st.secrets["media_player_drive"]["folder_id"]
    return None

def get_or_create_subfolder(service, parent_id, folder_name):
    """Verifica se uma subpasta existe. Se não, cria e retorna o ID."""
    query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and '{parent_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    else:
        # Cria a pasta se não existir
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        try:
            folder = service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
        except Exception as e:
            if "storageQuotaExceeded" in str(e):
                st.error(f"❌ Erro de Cota: Não foi possível criar a pasta `{folder_name}`. Por favor, crie-a manualmente no Google Drive.")
            return None

def get_nested_folder_id(service, root_id, folder_path):
    """Navega ou cria uma estrutura de pastas e retorna o ID da última."""
    current_id = root_id
    for folder_name in folder_path:
        current_id = get_or_create_subfolder(service, current_id, folder_name)
        if not current_id: return None
    return current_id

def find_file(service, filename, folder_id):
    """Procura o ID de um arquivo pelo nome dentro da pasta alvo."""
    # 1. Tenta busca exata (mais rápida)
    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    try:
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
    except Exception as e:
        print(f"Erro na busca exata (find_file): {e}")
        
    # 2. Fallback: Lista tudo e busca ignorando maiúsculas/minúsculas (Case Insensitive)
    try:
        query_all = f"'{folder_id}' in parents and trashed = false"
        results_all = service.files().list(q=query_all, fields="files(id, name)").execute()
        for f in results_all.get('files', []):
            if f['name'].lower() == filename.lower():
                return f['id']
    except Exception as e:
        print(f"Erro na busca fallback (find_file): {e}")
            
    return None

def load_json(filename, default_value=None, silent=False, folder_path=None):
    """Carrega um JSON de uma subpasta específica (default: ['data'])."""
    if folder_path is None:
        folder_path = ['data']
        
    service = get_drive_service()
    root_id = get_folder_id()
    
    try:
        if not service or not root_id:
            return default_value or {}

        # 1. Tenta buscar na estrutura de pastas especificada
        target_folder_id = get_nested_folder_id(service, root_id, folder_path)
        file_id = None
        if target_folder_id:
            file_id = find_file(service, filename, target_folder_id)
        
        # 2. Fallback: Se não achar em 'data', tenta na raiz (caso o usuário não tenha movido)
        if not file_id:
            file_id = find_file(service, filename, root_id)

        if not file_id:
            if filename == "alunos.json":
                st.warning(f"⚠️ O arquivo `{filename}` não foi encontrado no Google Drive (nem na pasta 'data', nem na raiz). Verifique o nome e o upload.")
            return default_value or {}

        # Verifica se é um Google Doc (o que causaria erro de leitura)
        file_meta = service.files().get(fileId=file_id, fields='mimeType').execute()
        if file_meta.get('mimeType', '').startswith('application/vnd.google-apps'):
            st.error(f"❌ Erro Crítico: O arquivo `{filename}` no Drive é um **Documento Google** (GDoc/GSheet), não um arquivo JSON real.")
            st.info("👉 **Solução:** Exclua esse arquivo do Drive. No seu computador, crie o arquivo no Bloco de Notas, salve como .json e faça o upload novamente.")
            return default_value or {}

        content = service.files().get_media(fileId=file_id).execute()
        
        # Tenta decodificar com diferentes codificações (UTF-8, Latin-1/ANSI) para evitar erros
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']
        
        for encoding in encodings:
            try:
                return json.loads(content.decode(encoding))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        
        # Se falhou em todos, mostra o início do arquivo para diagnóstico
        if not silent:
            st.error(f"❌ O arquivo `{filename}` existe, mas o conteúdo não é um JSON válido.")
            try:
                snippet = content.decode('latin-1')[:200]
                st.code(snippet, language="text")
            except:
                st.write("Não foi possível exibir o conteúdo do arquivo.")
        return default_value or {}
    except Exception as e:
        # Loga o erro no console para debug, mas não exibe erro visual para não travar o fluxo se for algo temporário
        print(f"Erro ao carregar {filename} do Drive: {e}")
        return default_value or {}

def save_json(filename, data, folder_path=None):
    """Salva um arquivo JSON em uma subpasta específica (default: ['data'])."""
    if folder_path is None:
        folder_path = ['data']
        
    service = get_drive_service()
    root_id = get_folder_id()
    
    if not service or not root_id:
        return False

    # Garante que salva na estrutura de pastas
    target_folder_id = get_nested_folder_id(service, root_id, folder_path)
    if not target_folder_id:
        return False

    file_id = find_file(service, filename, target_folder_id)
    
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    media = MediaIoBaseUpload(io.BytesIO(json_str.encode('utf-8')), mimetype='application/json')

    try:
        if file_id:
            # Atualiza arquivo existente
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            # Cria novo arquivo
            file_metadata = {'name': filename, 'parents': [target_folder_id]}
            service.files().create(body=file_metadata, media_body=media).execute()
        return True
    except Exception as e:
        error_str = str(e)
        if "storageQuotaExceeded" in error_str or "Service Accounts do not have storage quota" in error_str:
            st.error(f"❌ **Erro de Permissão (Cota Zero)**")
            st.warning(f"A Conta de Serviço não pode criar o arquivo `{filename}` porque não possui cota de armazenamento própria (comum em contas @gmail.com).")
            st.info(f"👉 **Solução:** Vá até a pasta `data` no Google Drive e crie manualmente um arquivo vazio (pode ser um arquivo de texto renomeado) com o nome exato **`{filename}`**. O sistema conseguirá atualizá-lo.")
        else:
            st.error(f"Erro ao salvar {filename} no Drive: {e}")
        return False

def list_files_in_subfolder(subfolder_name, mime_type=None):
    """Lista arquivos dentro de uma subpasta específica (ex: 'pdf')."""
    service = get_drive_service()
    root_id = get_folder_id()
    
    if not service or not root_id:
        return []
        
    target_folder_id = get_or_create_subfolder(service, root_id, subfolder_name)
    
    query = f"'{target_folder_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
        
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def list_files_in_path(folder_path, mime_type=None):
    """Lista arquivos dentro de uma estrutura de pastas (ex: ['data', 'frequencia'])."""
    service = get_drive_service()
    root_id = get_folder_id()
    
    if not service or not root_id:
        return []
        
    target_id = get_nested_folder_id(service, root_id, folder_path)
    if not target_id:
        return []
    
    query = f"'{target_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
        
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def list_files_with_link(folder_id=None):
    """Lista arquivos de uma pasta retornando metadados para media player."""
    service = get_drive_service()
    if not service: return []
    
    target_id = folder_id if folder_id else get_folder_id()
    if not target_id: return []
    
    query = f"'{target_id}' in parents and trashed = false"
    # Busca ID, Nome, Tipo MIME, Link da Thumbnail e WebContentLink
    results = service.files().list(q=query, fields="files(id, name, mimeType, thumbnailLink, webContentLink)").execute()
    return results.get('files', [])

def upload_file(file_obj, filename, folder_id=None):
    """Faz upload de um arquivo para o Google Drive."""
    service = get_drive_service()
    if not service: return None
    
    target_id = folder_id if folder_id else get_folder_id()
    if not target_id: return None

    file_metadata = {'name': filename, 'parents': [target_id]}
    mimetype = getattr(file_obj, 'type', 'application/octet-stream')
    
    media = MediaIoBaseUpload(file_obj, mimetype=mimetype, resumable=True)

    try:
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"Erro no upload: {e}")
        return None

def download_file_bytes(file_id):
    """Baixa o conteúdo de um arquivo do Drive como bytes."""
    service = get_drive_service()
    if not service: return None
    
    request = service.files().get_media(fileId=file_id)
    file_io = io.BytesIO()
    downloader = MediaIoBaseDownload(file_io, request)
    
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        
    file_io.seek(0)
    return file_io