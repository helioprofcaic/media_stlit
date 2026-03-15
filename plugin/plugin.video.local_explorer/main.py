import sys
import os
import urllib.parse
import json
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

# Tenta obter o handle do plugin, fallback para 1 se executado fora do padrão
try:
    HANDLE = int(sys.argv[1])
except:
    HANDLE = 1

# Extensões de vídeo suportadas
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mp3', '.wav', '.m4v', '.strm')

# --- Sistema de Favoritos ---
ADDON = xbmcaddon.Addon()

def get_favorites_file():
    profile = ADDON.getAddonInfo('profile')
    if not os.path.exists(profile):
        os.makedirs(profile)
    return os.path.join(profile, 'favorites.json')

def get_favorites():
    try:
        with open(get_favorites_file(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_favorites(items):
    try:
        with open(get_favorites_file(), 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=4)
    except Exception as e:
        xbmc.log(f"Erro ao salvar favoritos: {e}", xbmc.LOGERROR)

def add_favorite(path):
    items = get_favorites()
    if any(i['path'] == path for i in items):
        xbmcgui.Dialog().notification('Favoritos', 'Pasta já está nos favoritos', xbmcgui.NOTIFICATION_INFO)
        return
    
    name = os.path.basename(path) or path
    items.append({'name': name, 'path': path})
    save_favorites(items)
    xbmcgui.Dialog().notification('Favoritos', 'Adicionado aos favoritos', xbmcgui.NOTIFICATION_INFO)

def remove_favorite(path):
    items = get_favorites()
    items = [i for i in items if i['path'] != path]
    save_favorites(items)
    xbmcgui.Dialog().notification('Favoritos', 'Removido dos favoritos', xbmcgui.NOTIFICATION_INFO)
    xbmc.executebuiltin('Container.Refresh')

def list_favorites():
    items = get_favorites()
    for item in items:
        li = xbmcgui.ListItem(label=item['name'])
        li.setArt({'icon': 'DefaultFolder.png'})
        
        rm_url = f"{sys.argv[0]}?{urllib.parse.urlencode({'action': 'remove_favorite', 'path': item['path']})}"
        li.addContextMenuItems([('Remover dos Favoritos', f"XBMC.RunPlugin({rm_url})")])
        
        url = f"{sys.argv[0]}?{urllib.parse.urlencode({'action': 'list_dir', 'path': item['path']})}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)

def get_drives():
    """Lista as unidades de armazenamento disponíveis e pastas comuns."""
    drives = []
    
    # Adiciona a pasta raiz do projeto (útil em ambientes como Streamlit Cloud)
    project_root = os.getcwd()
    drives.append(("Pasta do Projeto (Atual)", project_root))
    
    # Adiciona pasta do usuário (Home) como atalho conveniente
    home = os.path.expanduser("~")
    drives.append(("Pasta do Usuário (Home)", home))

    if sys.platform == 'win32':
        import string
        from ctypes import windll
        
        try:
            # Obtém bitmask de drives lógicos
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append((f"Disco Local ({letter}:)", f"{letter}:\\"))
                bitmask >>= 1
        except Exception as e:
            xbmc.log(f"Erro ao listar drives Windows: {e}", xbmc.LOGERROR)
    else:
        # Linux/Unix/Mac
        drives.append(("Raiz do Sistema (/)", "/"))
        # Verifica montagens comuns de mídia externa
        for path in ["/media", "/mnt", "/Volumes"]:
            if os.path.exists(path):
                drives.append((f"Mídia Externa ({path})", path))
                
    return drives

def list_root():
    """Exibe o menu principal com as unidades."""
    # Item de Favoritos
    li_fav = xbmcgui.ListItem(label="[ Favoritos ]")
    li_fav.setArt({'icon': 'DefaultFavorites.png'})
    url_fav = f"{sys.argv[0]}?{urllib.parse.urlencode({'action': 'list_favorites'})}"
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=url_fav, listitem=li_fav, isFolder=True)

    drives = get_drives()
    
    for label, path in drives:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': 'DefaultHardDisk.png'})
        
        url_params = urllib.parse.urlencode({'action': 'list_dir', 'path': path})
        url = f"{sys.argv[0]}?{url_params}"
        
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_directory(path):
    """Lista arquivos e pastas dentro de um diretório."""
    try:
        xbmc.log(f"Listando diretório: {path}", xbmc.LOGNOTICE)
        items = os.listdir(path)
        # Ordena: Pastas primeiro, depois arquivos (case insensitive)
        items.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))
        
        for item in items:
            full_path = os.path.join(path, item)
            
            if os.path.isdir(full_path):
                li = xbmcgui.ListItem(label=item)
                li.setArt({'icon': 'DefaultFolder.png'})
                
                # Menu de contexto para adicionar aos favoritos
                fav_url = f"{sys.argv[0]}?{urllib.parse.urlencode({'action': 'add_favorite', 'path': full_path})}"
                li.addContextMenuItems([('Adicionar aos Favoritos', f"XBMC.RunPlugin({fav_url})")])
                
                url_params = urllib.parse.urlencode({'action': 'list_dir', 'path': full_path})
                url = f"{sys.argv[0]}?{url_params}"
                
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
            
            elif item.lower().endswith(VIDEO_EXTENSIONS):
                li = xbmcgui.ListItem(label=item)
                li.setInfo('video', {'title': item, 'mediatype': 'video'})
                li.setProperty('IsPlayable', 'true')
                
                if item.lower().endswith('.strm'):
                    li.setArt({'icon': 'DefaultNetwork.png'})
                else:
                    li.setArt({'icon': 'DefaultVideo.png'})
                
                # Para arquivos locais, passamos o path direto para play
                url_params = urllib.parse.urlencode({'action': 'play', 'path': full_path})
                url = f"{sys.argv[0]}?{url_params}"
                
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=False)
                
    except Exception as e:
        xbmcgui.Dialog().notification('Erro de Acesso', str(e), xbmcgui.NOTIFICATION_ERROR)

    xbmcplugin.endOfDirectory(HANDLE)

def router(param_string):
    params = urllib.parse.parse_qs(param_string)
    action = params.get('action', [None])[0]
    
    if action == 'list_dir':
        list_directory(params.get('path', [''])[0])
    elif action == 'list_favorites':
        list_favorites()
    elif action == 'add_favorite':
        add_favorite(params.get('path', [''])[0])
    elif action == 'remove_favorite':
        remove_favorite(params.get('path', [''])[0])
    elif action == 'play':
        # Resolve o caminho local para o player tocar
        path = params.get('path', [''])[0]
        li = xbmcgui.ListItem(path=path)
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
    else:
        list_root()

if __name__ == '__main__':
    # Tratamento seguro para sys.argv
    param_string = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    router(param_string)