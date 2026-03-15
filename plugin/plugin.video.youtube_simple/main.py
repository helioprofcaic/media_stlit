import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import requests
import json
import random
import os
import time
import re
from io import BytesIO

# Tenta importar google_storage do ambiente pai (Streamlit)
try:
    import google_storage
except ImportError:
    google_storage = None

# Arquivo de cache para instâncias
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(PLUGIN_DIR, 'instances.json')

# Lista de canais brasileiros por categoria
BRAZILIAN_CHANNELS = {
    "noticias": ("📰 Notícias", [
        {"name": "g1", "id": "UC-y-3fTP1JgA44Z9kgg3pNA", "icon": "https://yt3.googleusercontent.com/Co_p-9YUC9I-tS2fnq0g2jJj5Cfl1sT4J2j_1j_1j_1j_1j_1j_1j_1j_1j=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "Band Jornalismo", "id": "UC635tYlT_gI3rD3e1gr5vjQ", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "CNN Brasil", "id": "UCvdwhh_tA_2sUMNX_LskQxQ", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "Jovem Pan News", "id": "UCorB22oM2_Z2-wN3dY3qE1g", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
    ]),
    "ciencia": ("🔬 Ciência e Curiosidades", [
        {"name": "Ciência Todo Dia", "id": "UCn9bO0S3Lp3m9jrkD6E-2dg", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "Canal do Pirula", "id": "UCdGpd0gNn38UKsMvT_h9RyA", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "SpaceToday", "id": "UC_Fk7hLmc9k3yMvjc6xXejg", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
    ]),
    "podcasts": ("🎙️ Podcasts", [
        {"name": "Flow Podcast", "id": "UC4ncvgh5hFr5O83MH7-jRJg", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "Podpah", "id": "UCep_eI-gLe0c2i1zGv4b2gA", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
    ]),
    "musica": ("🎵 Música", [
        {"name": "Canal KondZilla", "id": "UCffD2RlL2m72oJtN88mI3vQ", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "GR6 EXPLODE", "id": "UC3gPcf3gA0g3i3gJ1D3wG1w", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
        {"name": "Jovem Pan FM", "id": "UCgS-6v9A32v3aeL2iL3Ew-w", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
    ]),
    "diversos": ("⭐ Diversos", [
        {"name": "Tamir Filipe", "id": "UCoyD03n02f5iM1QjBw6T9Lg", "icon": "https://yt3.googleusercontent.com/ytc/AIdro_k-pYJ3E3O-5iR_3Qe_y-p_F2EaZ_EaZ_EaZ_E=s176-c-k-c0x00ffffff-no-rj"},
    ])
}

# Lista de fallback (caso o cache falhe ou não exista)
FALLBACK_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.jing.rocks",
    "https://invidious.nerdvpn.de",
    "https://yewtu.be",
    "https://vid.puffyan.us",
    "https://invidious.drgns.space",
    "https://inv.tux.pizza"
]

# Lista de Tópicos Sugeridos (Chips do YouTube)
TOPICS_LIST = [
    ("♾️ Tudo", "trending"), # Mapeia para Em Alta
    ("🎙️ Podcasts", "Podcasts"),
    ("🎵 Música", "Música"),
    ("📰 Notícias", "Notícias"),
    ("🗣️ Debates", "Debates"),
    ("🤖 Inteligência artificial", "Inteligência artificial"),
    ("🕹️ Década de 1980", "Década de 1980"),
    ("🎛️ Mixes", "Music Mix"),
    ("📜 Lista de reprodução", "Playlists"),
    ("🔴 Ao vivo", "Ao vivo"),
    ("💻 Sistema operacional", "Sistema operacional"),
    ("📈 Economia", "Economia"),
    ("👨‍💻 Engenharia de software", "Engenharia de software"),
    ("🥁 Samba", "Samba"),
    ("🧠 Teorias", "Teorias"),
    ("zz Cálculo", "Cálculo"), # zz para ordenar se necessário, ou manter texto puro
    ("☕ Chill out", "Chill out music"),
    ("🆕 Enviados recentemente", "recent"), # Lógica customizada
    ("✨ Novidades para você", "trending")
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

    # Garante que as instâncias de fallback estejam na lista (backup)
    for fb in FALLBACK_INSTANCES:
        if fb not in instances:
            instances.append(fb)
    
    success = False
    last_error = None
    
    # Desabilita warnings de SSL (necessário pois usaremos verify=False)
    try:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    except:
        pass

    for base_url in instances:
        try:
            url = f"{base_url}{endpoint}"
            # Timeout curto para pular rápido se estiver lento
            r = requests.get(url, params=params, timeout=10, verify=False)
            
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

def list_channel_categories():
    """Lista as categorias de canais brasileiros."""
    for category_id, (category_name, _) in BRAZILIAN_CHANNELS.items():
        li = xbmcgui.ListItem(label=category_name)
        url = get_url(action='list_channels', category=category_id)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_channels_by_category(category_id):
    """Lista os canais de uma categoria específica."""
    if category_id not in BRAZILIAN_CHANNELS:
        return

    _, channels = BRAZILIAN_CHANNELS[category_id]
    for channel in channels:
        li = xbmcgui.ListItem(label=channel['name'])
        icon = channel.get('icon')
        if icon:
            li.setArt({'thumb': icon, 'icon': icon})
        
        # A URL aponta para a lista de vídeos do canal
        url = get_url(action='list_channel_videos', channel_id=channel['id'])
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_local_playlists():
    """Lista arquivos .strm da pasta playlists local."""
    # A pasta playlists está na raiz do projeto (dois níveis acima de plugin/plugin.video...)
    # Como o streamlit roda da raiz, os.getcwd() geralmente é a raiz do projeto.
    playlists_dir = os.path.join(os.getcwd(), 'playlists')
    
    if not os.path.exists(playlists_dir):
        xbmcgui.Dialog().notification("Aviso", "Pasta 'playlists' não encontrada.")
        return

    try:
        files = [f for f in os.listdir(playlists_dir) if f.lower().endswith('.strm')]
    except Exception:
        files = []
    
    if not files:
        xbmcgui.Dialog().notification("Aviso", "Nenhum arquivo .strm encontrado.")
        return

    for f in files:
        path = os.path.join(playlists_dir, f)
        try:
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read().strip()
            
            # Tenta extrair ID do YouTube (suporta v=ID, embed/ID, youtu.be/ID)
            match = re.search(r'(?:v=|/)([0-9A-Za-z_-]{11})', content)
            if match:
                video_id = match.group(1)
                title = os.path.splitext(f)[0]
                
                li = xbmcgui.ListItem(label=f"📄 {title}")
                li.setInfo('video', {'title': title})
                li.setArt({'icon': 'DefaultNetwork.png'})
                
                url = get_url(action='play', video_id=video_id)
                xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=False)
        except:
            pass
    
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_topics():
    """Lista os tópicos sugeridos como se fossem pastas."""
    for label, query in TOPICS_LIST:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': 'DefaultAddonSearch.png'})
        
        if query == "trending":
            # Redireciona para a função existente de Trending
            url = get_url(action='trending')
        elif query == "recent":
            # Busca genérica ordenada por data (simulação)
            url = get_url(action='search_topic', query="Novidades", sort_by="date")
        else:
            # Busca normal pelo termo
            url = get_url(action='search_topic', query=query)
            
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
    
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def search_topic(query, sort_by=None):
    """Wrapper para realizar a busca de um tópico."""
    params = {'q': query, 'type': 'video'}
    if sort_by:
        params['sort_by'] = sort_by
    list_videos("/api/v1/search", params)

def save_topic_to_drive(label, query):
    """Cria um arquivo .strm com o link do tópico e envia para o Google Drive."""
    if not google_storage:
        xbmcgui.Dialog().notification("Erro", "Módulo Google Drive não disponível.")
        return

    # Limpa caracteres especiais do nome do arquivo
    clean_name = re.sub(r'[^\w\s-]', '', label).strip()
    filename = f"{clean_name}.strm"
    
    # Determina a URL do plugin que gera essa lista
    if query == "trending":
        target_url = get_url(action='trending')
    elif query == "recent":
        target_url = get_url(action='search_topic', query="Novidades", sort_by="date")
    else:
        target_url = get_url(action='search_topic', query=query)
    
    # Cria o arquivo em memória com a URL como conteúdo
    file_content = target_url.encode('utf-8')
    file_obj = BytesIO(file_content)
    file_obj.name = filename
    file_obj.type = 'text/plain'
    
    # Upload usando a função existente do google_storage
    file_id = google_storage.upload_file(file_obj, filename)
    
    if file_id:
        xbmcgui.Dialog().notification("Sucesso", f"Playlist salva no Drive!")
    else:
        xbmcgui.Dialog().notification("Erro", "Falha ao salvar no Drive.")

def list_save_menu():
    """Lista os tópicos com a ação de salvar."""
    for label, query in TOPICS_LIST:
        li = xbmcgui.ListItem(label=f"💾 Salvar: {label}")
        li.setArt({'icon': 'DefaultAddonService.png'})
        
        url = get_url(action='save_topic', label=label, query=query)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=False)
    
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

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
    elif action == 'channels':
        list_channel_categories()
    elif action == 'list_channels':
        list_channels_by_category(params.get('category'))
    elif action == 'list_channel_videos':
        channel_id = params.get('channel_id')
        if channel_id:
            list_videos(f"/api/v1/channels/{channel_id}/videos", {})
    elif action == 'local_playlists':
        list_local_playlists()
    elif action == 'topics':
        list_topics()
    elif action == 'search_topic':
        search_topic(params.get('query'), params.get('sort_by'))
    elif action == 'save_menu':
        list_save_menu()
    elif action == 'save_topic':
        save_topic_to_drive(params.get('label'), params.get('query'))
    else:
        # Menu Principal
        li = xbmcgui.ListItem(label="🔥 Em Alta (Brasil)")
        url = get_url(action='trending')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
        
        li = xbmcgui.ListItem(label="📺 Canais do Brasil")
        url = get_url(action='channels')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
        
        li = xbmcgui.ListItem(label="📂 Playlists Locais (.strm)")
        url = get_url(action='local_playlists')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
        
        li = xbmcgui.ListItem(label="🏷️ Explorar Tópicos")
        url = get_url(action='topics')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
        
        li = xbmcgui.ListItem(label="💾 Salvar Playlists no Drive")
        url = get_url(action='save_menu')
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