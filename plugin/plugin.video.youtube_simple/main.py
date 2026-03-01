import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import requests
import json
import random
import os
import time

# Arquivo de cache para instâncias
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(PLUGIN_DIR, 'instances.json')

# Lista de fallback (caso o cache falhe ou não exista)
FALLBACK_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.jing.rocks",
    "https://invidious.nerdvpn.de",
    "https://yewtu.be"
]

def get_url(**kwargs):
    """Gera a URL interna do plugin com parâmetros."""
    return "{0}?{1}".format(sys.argv[0], urllib.parse.urlencode(kwargs))

def get_instances():
    """Carrega instâncias do cache ou usa fallback."""
    instances = []
    # Tenta carregar do cache se existir
    if os.path.exists(CACHE_FILE):
        try:
            # Validade de 24h (opcional, aqui apenas lê se existir)
            with open(CACHE_FILE, 'r') as f:
                instances = json.load(f)
        except:
            pass
    
    if not instances:
        instances = FALLBACK_INSTANCES
    
    return instances

def update_instances_cache():
    """Baixa nova lista de instâncias da API oficial e salva em cache."""
    try:
        # Usa a lista do gitetsu/invidious-instances-upptime (monitoramento de uptime)
        url = "https://raw.githubusercontent.com/gitetsu/invidious-instances-upptime/master/history/summary.json"
        r = requests.get(url, timeout=15)
        data = r.json()
        
        new_list = []
        for item in data:
            # Upptime summary.json structure: {"url": "...", "status": "up", ...}
            if item.get('status') == 'up':
                uri = item.get('url')
                if uri:
                    new_list.append(uri.rstrip('/'))
        
        if new_list:
            # Embaralha para balanceamento
            random.shuffle(new_list)
            # Salva no arquivo (Top 15)
            with open(CACHE_FILE, 'w') as f:
                json.dump(new_list[:15], f)
            
            xbmcgui.Dialog().notification("Sucesso", f"{len(new_list[:15])} servidores atualizados!")
            return True
        else:
            xbmcgui.Dialog().notification("Erro", "Nenhuma instância encontrada na API.")
            return False
    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha ao atualizar: {str(e)}")
        return False

def list_videos(endpoint, params):
    """Tenta buscar vídeos rotacionando instâncias em caso de erro."""
    
    instances = get_instances()
    # Embaralha instâncias para balanceamento
    random.shuffle(instances)
    
    success = False
    last_error = None
    
    for base_url in instances:
        try:
            url = f"{base_url}{endpoint}"
            # Timeout curto para pular rápido se estiver lento
            r = requests.get(url, params=params, timeout=10)
            
            if r.status_code != 200:
                continue
                
            results = r.json()
            
            # Se a lista vier vazia, pode ser erro da instância, tenta outra
            if not results:
                continue

            for item in results:
                if item.get('type') != 'video': continue
                
                video_id = item.get('videoId')
                title = item.get('title')
                author = item.get('author')
                
                # Thumbnail
                thumb = ""
                thumbnails = item.get('videoThumbnails', [])
                if thumbnails:
                    # Tenta pegar qualidade média/alta
                    for t in thumbnails:
                        if t.get('quality') == 'medium':
                            thumb = t['url']
                            break
                    if not thumb:
                        thumb = thumbnails[0]['url']
                
                li = xbmcgui.ListItem(label=title)
                li.setInfo('video', {'title': title, 'artist': author, 'plot': item.get('description', '')})
                if thumb:
                    li.setArt({'thumb': thumb, 'icon': thumb, 'fanart': thumb})
                li.setProperty('IsPlayable', 'true')
                
                url_play = get_url(action='play', video_id=video_id)
                xbmcplugin.addDirectoryItem(int(sys.argv[1]), url_play, li, isFolder=False)
            
            xbmcplugin.endOfDirectory(int(sys.argv[1]))
            success = True
            break
            
        except Exception as e:
            last_error = e
            print(f"Falha na instância {base_url}: {e}")
            continue
    
    if not success:
        # Se falhar em todas, lança erro para aparecer na interface do Streamlit
        raise Exception(f"Todas as instâncias do Invidious falharam. Último erro: {last_error}")

def play(video_id):
    # URL direta do YouTube (o Streamlit player resolve)
    url = f"https://www.youtube.com/watch?v={video_id}"
    li = xbmcgui.ListItem(path=url)
    xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, li)

def router(args):
    """Roteador de URL do plugin."""
    params = dict(urllib.parse.parse_qsl(args))
    action = params.get('action')
    
    if action == 'search':
        kb = xbmcgui.Dialog()
        term = kb.input("Buscar no YouTube", type=xbmcgui.INPUT_ALPHANUM)
        if term:
            list_videos("/api/v1/search", {'q': term, 'type': 'video'})
    elif action == 'play':
        play(params.get('video_id'))
    elif action == 'trending':
        list_videos("/api/v1/trending", {'region': 'BR'})
    elif action == 'update_servers':
        update_instances_cache()
    else:
        # Menu Principal
        li = xbmcgui.ListItem(label="🔥 Em Alta (Brasil)")
        url = get_url(action='trending')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
        
        li = xbmcgui.ListItem(label="🔍 Buscar")
        url = get_url(action='search')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
        
        li = xbmcgui.ListItem(label="🔄 Atualizar Servidores")
        url = get_url(action='update_servers')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=False)

        xbmcplugin.endOfDirectory(int(sys.argv[1]))

if __name__ == '__main__':
    # Remove o '?' inicial se existir
    args = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    router(args)