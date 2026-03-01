import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import requests
import json

# URL da API (Radio Browser)
API_URL = "https://de1.api.radio-browser.info/json/stations"

def get_url(**kwargs):
    """Gera a URL interna do plugin com parâmetros."""
    return "{0}?{1}".format(sys.argv[0], urllib.parse.urlencode(kwargs))

def list_categories():
    """Menu Principal."""
    # Busca
    li = xbmcgui.ListItem(label="🔍 Buscar Rádio")
    url = get_url(action='search')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

    # Top Brasil
    li = xbmcgui.ListItem(label="🇧🇷 Top Brasil")
    url = get_url(action='country', country='Brazil')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
    
    # Top EUA
    li = xbmcgui.ListItem(label="🇺🇸 Top USA")
    url = get_url(action='country', country='United States')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

    # Estilos (Tags)
    li = xbmcgui.ListItem(label="🎸 Por Estilo (Rock, Pop, Jazz...)")
    url = get_url(action='tags')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_tags():
    """Lista categorias de música."""
    tags = ['Pop', 'Rock', 'Jazz', 'Classical', 'News', 'Talk', 'Dance', 'Electronic', 'Sertanejo', 'Funk']
    for tag in tags:
        li = xbmcgui.ListItem(label=f"🎵 {tag}")
        url = get_url(action='by_tag', tag=tag.lower())
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def search_radio():
    """Abre teclado para busca."""
    kb = xbmcgui.Dialog()
    term = kb.input("Nome da Rádio", type=xbmcgui.INPUT_ALPHANUM)
    if not term: return
    fetch_stations({'name': term, 'limit': 30})

def fetch_stations(api_params):
    """Busca estações na API e lista no Kodi/Streamlit."""
    try:
        # Parâmetros padrão da API
        params = {'hidebroken': 'true', 'order': 'clickcount', 'reverse': 'true'}
        params.update(api_params)
        
        # Faz a requisição
        r = requests.get(f"{API_URL}/search", params=params, timeout=10)
        r.raise_for_status()
        stations = r.json()
        
        if not stations:
            xbmcgui.Dialog().notification("Aviso", "Nenhuma rádio encontrada.")
            return

        for s in stations:
            name = s.get('name', '').strip()
            url = s.get('url_resolved') or s.get('url')
            icon = s.get('favicon') or ''
            country = s.get('country', '')
            
            if not url: continue
            
            # Cria o item de áudio
            li = xbmcgui.ListItem(label=name)
            li.setInfo('music', {'title': name, 'artist': country})
            li.setArt({'thumb': icon, 'icon': icon})
            li.setProperty('IsPlayable', 'true')
            
            # Adiciona à lista
            xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=False)
            
        xbmcplugin.endOfDirectory(int(sys.argv[1]))
    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha na API: {str(e)}")

def router(args):
    """Roteador de URL do plugin."""
    params = dict(urllib.parse.parse_qsl(args))
    action = params.get('action')
    
    if action == 'search':
        search_radio()
    elif action == 'country':
        fetch_stations({'country': params.get('country'), 'limit': 50})
    elif action == 'tags':
        list_tags()
    elif action == 'by_tag':
        fetch_stations({'tag': params.get('tag'), 'limit': 50})
    else:
        list_categories()

if __name__ == '__main__':
    # Remove o '?' inicial se existir
    args = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    router(args)
