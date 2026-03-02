import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import requests
import json
import os
import xbmc

# URL da API (Radio Browser)
BASE_API = "https://de1.api.radio-browser.info"
API_URL = f"{BASE_API}/json/stations"

# Caminhos de Cache
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCES_DIR = os.path.join(PLUGIN_DIR, 'resources')
COUNTRIES_FILE = os.path.join(RESOURCES_DIR, 'countries.json')
TAGS_FILE = os.path.join(RESOURCES_DIR, 'tags.json')

# Lista de Rádios Personalizadas (Adicionadas Manualmente)
CUSTOM_STATIONS = [
    {"name": "Arrow Classic Rock", "url": "http://stream.gal.io/arrow", "country": "NL", "image": "https://www.arrow.nl/wp-content/uploads/2020/08/logo.png"},
    {"name": "Blasmusikradio mit Bernd", "url": "https://stream.laut.fm/blasmusikradio_mit_bernd", "country": "DE", "image": "https://assets.laut.fm/b22749b7fdb382b8912269e3d8054380?t=_120x120"},
    {"name": "Fun Radio", "url": "http://stream.funradio.sk:8000/fun128.mp3", "country": "SK", "image": ""},
    {"name": "Hard Rock Radio FM", "url": "http://67.249.184.45:8015/listen.pls", "country": "US", "image": ""},
    {"name": "Polskie Radio Bialystok", "url": "http://stream4.nadaje.com:15476/radiobialystok", "country": "PL", "image": "http://www.radio.bialystok.pl/favicon.ico"},
    {"name": "psyradio * fm - progressive", "url": "http://streamer.psyradio.org:8010/;listen.mp3", "country": "DE", "image": "https://lh6.ggpht.com/dU5W-XpgWgEgtIt3Ho990I9bre5IZTq7AK2ffSt_bXTDTNQ6eUkTG-WqERh6c_EHPb8=w300"},
    {"name": "Radio Bruno Pentasport Fiorentina", "url": "https://stream3.xdevel.com/audio6s975355-281/stream/icecast.audio", "country": "IT", "image": "https://www.radiobruno.it/wp-content/uploads/2023/10/logo-148-90-black1.png"},
    {"name": "Radio Capital", "url": "https://4c4b867c89244861ac216426883d1ad0.msvdn.net/radiocapital/radiocapital/master_ma.m3u8", "country": "IT", "image": "https://www.capital.it/wp-content/themes/network-capital/favicon.ico"},
    {"name": "Radio Margherita", "url": "https://streaming.radiomargherita.com/stream/radiomargherita", "country": "IT", "image": "http://www.radiomargherita.com/favicon.ico"},
    {"name": "Radio Record - Russian Gold", "url": "https://radiorecord.hostingradio.ru/russiangold96.aacp", "country": "RU", "image": "https://www.radiorecord.ru/icons/apple-touch-icon.png"},
    {"name": "RTL France", "url": "http://streaming.radio.rtl.fr/rtl-1-44-128", "country": "FR", "image": "https://www.radio.de/images/broadcasts/88/5b/5168/c300.png"},
    {"name": "Tick Tock Radio - 1950", "url": "https://streaming.ticktock.radio/tt/1950/icecast.audio", "country": "FI", "image": "https://ticktock.radio/static/assets/img/apple-icon-120x120.png"},
    {"name": "WDR Sportschau", "url": "http://wdr-sportschau-liga2konferenz.icecastssl.wdr.de/wdr/sportschau/liga2konferenz/mp3/high", "country": "DE", "image": ""},
    {"name": "Европа Плюс", "url": "http://ep256.hostingradio.ru:8052/europaplus256.mp3", "country": "RU", "image": "http://liveam.tv/img/2494.jpg"},
    {"name": "ROCKANTENNE Alternative", "url": "https://stream.rockantenne.de/alternative/stream/mp3", "country": "DE", "image": "https://www.rockantenne.de/logos/station-rock-antenne/apple-touch-icon.png"},
    {"name": "Squirrel FM", "url": "http://s25.myradiostream.com:10092/stream", "country": "CA", "image": "https://media.live365.com/download/b6b2cf5d-7596-471f-8aa4-fb4edd25612f.jpg"},
    {"name": "Radio Disney 94.3 (Argentina)", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/DISNEY_ARG_BA_ADP.aac", "country": "AR", "image": "https://cdn-profiles.tunein.com/s13659/images/logog.png"},
    {"name": "88.9 NOTICIAS", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHMFMAAC_SC.aac", "country": "MX", "image": "https://static.mytuner.mobi/media/tvos_radios/466/889-noticias.62cade58.png"},
    {"name": "ALFA 91.3", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHFAJ_FMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/4dmFn1tf/alfa.png"},
    {"name": "AMOR 95.3", "url": "https://22973.live.streamtheworld.com:443/XHSHFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/FKgrF3cw/amor.jpg"},
    {"name": "AZUL 89", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/ACIR24_s01AAC.aac", "country": "MX", "image": "https://i.iheart.com/v3/re/new_assets/5bc5ed95c7977ca1c9302289"},
    {"name": "BEAT 100.9", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHSONFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/C15C4837/beat-2025.jpg"},
    {"name": "CHILANGO RADIO", "url": "https://stream.radio.co/s938b68214/listen", "country": "MX", "image": "https://i.iheart.com/v3/re/assets.streams/68507f96166c04a064910e82"},
    {"name": "EL FONÓGRAFO", "url": "https://18313.live.streamtheworld.com:443/XEJP_AMAAC.aac", "country": "MX", "image": "https://i.iheart.com/v3/re/new_assets/5ef0cb167ec97a064f3322d1"},
    {"name": "EXA FM 104.9", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHEXAAAC.aac", "country": "MX", "image": "https://i.postimg.cc/NGpmV3PJ/exafm.jpg"},
    {"name": "GRUPO FÓRMULA 103.3", "url": "https://mdstrm.com/audio/6102ce7ef33d0b0830ec3adc/live.m3u8", "country": "MX", "image": "https://thumbnail.anii.io/mx/radio-formula-103-3-fm-mexico.webp"},
    {"name": "HERALDO RADIO", "url": "https://stream.radiojar.com/0pqyt47etbkvv", "country": "MX", "image": "https://i.iheart.com/v3/re/assets.streams/69123130bb13926ddacf04e4"},
    {"name": "IBERO 90.9", "url": "http://noasrv.caster.fm:10182/live", "country": "MX", "image": "https://cdn-profiles.tunein.com/s50611/images/logod.png"},
    {"name": "IMAGEN RADIO", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XEDAFMAAC.aac", "country": "MX", "image": "https://thumbnail.anii.io/mx/radio-imagen-90-5-fm-mexico.webp"},
    {"name": "JOYA 93.7", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XEJP_FMAAC.aac", "country": "MX", "image": "https://cdn-profiles.tunein.com/s24508/images/logod.jpg"},
    {"name": "LA COMADRE", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XELAMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/mD0WQyvV/la-comadre.png"},
    {"name": "LA KEBUENA", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/KEBUENAAAC.aac", "country": "MX", "image": "https://cdn-profiles.tunein.com/s25263/images/logod.png"},
    {"name": "LA MEJOR", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XERCFMAAC.aac", "country": "MX", "image": "https://static.wikia.nocookie.net/logopedia/images/a/aa/La_Mejor_logo_actual.png/revision/latest"},
    {"name": "LA Z 107.3", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XEQR_FMAAC.aac", "country": "MX", "image": "https://cdn-profiles.tunein.com/s24532/images/logod.jpg"},
    {"name": "LOS40 México", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/LOS40_MEXICOAAC.aac", "country": "MX", "image": "https://los40es00.epimg.net/iconos/v3.x/v1.0/cabeceras/logo_40.png"},
    {"name": "MATCH 99.3", "url": "https://27283.live.streamtheworld.com:443/XHPOPFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/BZkKfvtv/match.jpg"},
    {"name": "MIX 106.5", "url": "https://18443.live.streamtheworld.com:443/XHDFMFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/J4K5Xkqz/mix.jpg"},
    {"name": "MVS NOTICIAS", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHMVSFMAAC.aac", "country": "MX", "image": "https://i.iheart.com/v3/re/new_assets/5ee43258c4c5167991940231"},
    {"name": "OYE 89.7", "url": "http://playerservices.streamtheworld.com/api/livestream-redirect/XEOYEFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/FHjNX8q9/oye.jpg"},
    {"name": "RADIO DISNEY México", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHFOFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/0QzYbY7z/disney.png"},
    {"name": "RADIO FELICIDAD", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XEFRAMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/MpjBZP9H/radio-felicidad.jpg"},
    {"name": "RADIO IPN", "url": "https://broadcast.radio.ipn.mx/RadioIPN", "country": "MX", "image": "https://cdn-profiles.tunein.com/s10687/images/logod.png"},
    {"name": "RADIO UNAM", "url": "https://tv.radiohosting.online:9484/stream", "country": "MX", "image": "https://cdn-radiotime-logos.tunein.com/s24539d.png"},
    {"name": "ROCK EN ESPAÑOL", "url": "https://29309.live.streamtheworld.com:443/ACIR20_S01AAC.aac", "country": "MX", "image": "https://i.iheart.com/v3/re/new_assets/5bc5ed6ac7977ca1c9302285"},
    {"name": "SMOOTH JAZZ", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/ACIR22_s01AAC.aac", "country": "MX", "image": "https://i.iheart.com/v3/re/assets.streams/63ee5ccb23c81aa16510435a"},
    {"name": "STEREO CIEN", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHMMFMAAC.aac", "country": "MX", "image": "https://i.postimg.cc/9XDdyxHP/stereocien.png"},
    {"name": "STEREOREY", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/STEREOREYAAC.aac", "country": "MX", "image": "https://cdn-radiotime-logos.tunein.com/s220691d.png"},
    {"name": "UNIVERSAL 88.1", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/XHFO_FMAAC.aac", "country": "MX", "image": "https://cdn-profiles.tunein.com/s1171/images/logog.png"},
    {"name": "VOX Radio Hits", "url": "https://streamingcwsradio30.com/8292/vox", "country": "MX", "image": "https://i.postimg.cc/9fZ9LHcm/vox.png"},
    {"name": "W RADIO", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/W_RADIOAAC.aac", "country": "MX", "image": "https://cdn-profiles.tunein.com/s16553/images/logod.jpg"},
    {"name": "100 % - HANDSUP", "url": "https://club-high.rautemusik.fm/?ref=radiobrowser-100-handsup", "country": "DE", "image": "https://i.ibb.co/X5hMzFX/100-handsup.png"},
    {"name": "DJ & CLUB CHARTS", "url": "https://breakz-2012-high.rautemusik.fm/?ref=rb-djclubcharts", "country": "DE", "image": "https://i.ibb.co/P7QHpGB/DJ-CLUB-CHARTS-LOGO.png"}
]

def update_local_cache():
    """Baixa e salva os dados mais recentes da API."""
    if not os.path.exists(RESOURCES_DIR):
        os.makedirs(RESOURCES_DIR)

    updated = False
    # 1. Países
    try:
        r = requests.get(f"{BASE_API}/json/countries", timeout=30)
        r.raise_for_status()
        with open(COUNTRIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(r.json(), f, ensure_ascii=False)
        updated = True
    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha ao baixar países: {e}")

    # 2. Tags
    try:
        r = requests.get(f"{BASE_API}/json/tags", timeout=30)
        r.raise_for_status()
        with open(TAGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(r.json(), f, ensure_ascii=False)
        updated = True
    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha ao baixar tags: {e}")

    if updated:
        xbmcgui.Dialog().notification("Sucesso", "Cache de dados atualizado.")
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def get_url(**kwargs):
    """Gera a URL interna do plugin com parâmetros."""
    return "{0}?{1}".format(sys.argv[0], urllib.parse.urlencode(kwargs))

def list_categories():
    """Menu Principal."""
    # Busca
    li = xbmcgui.ListItem(label="🔍 Buscar Rádio")
    url = get_url(action='search')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

    # Lista Especial (Custom)
    li = xbmcgui.ListItem(label="⭐ Lista Especial (Rádios Extras)")
    url = get_url(action='custom')
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

    # Tags por País
    li = xbmcgui.ListItem(label="🌍 Por País (Ver Estilos)")
    url = get_url(action='list_countries')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

    # Atualizar Cache
    li = xbmcgui.ListItem(label="🔄 Atualizar Cache de Dados")
    url = get_url(action='update_cache')
    xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_tags():
    """Lista categorias de música."""
    tags = ['Pop', 'Rock', 'Jazz', 'Classical', 'News', 'Talk', 'Dance', 'Electronic', 'Sertanejo', 'Funk', 'Reggaeton', 'Forró', 'Pisadinha']
    for tag in tags:
        li = xbmcgui.ListItem(label=f"🎵 {tag}")
        url = get_url(action='by_tag', tag=tag.lower())
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_custom():
    """Lista as rádios adicionadas manualmente."""
    for s in CUSTOM_STATIONS:
        li = xbmcgui.ListItem(label=s['name'])
        li.setInfo('music', {'title': s['name'], 'artist': s['country']})
        
        icon = s.get('image', '')
        if icon:
            li.setArt({'thumb': icon, 'icon': icon})
        
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), s['url'], li, isFolder=False)
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

def list_countries():
    """Lista os países disponíveis no cache."""
    try:
        with open(COUNTRIES_FILE, 'r', encoding='utf-8') as f:
            countries = json.load(f)
        
        countries.sort(key=lambda x: x['name'])

        for country in countries:
            if country['stationcount'] > 10:
                label = f"{country['name']} ({country['stationcount']})"
                li = xbmcgui.ListItem(label=label)
                url = get_url(action='tags_by_country', country_code=country['iso_3166_1'], country_name=country['name'])
                xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

        xbmcplugin.endOfDirectory(int(sys.argv[1]))
    except FileNotFoundError:
        xbmcgui.Dialog().notification("Erro", "Cache de países não encontrado. Atualize o cache.")
        xbmcplugin.endOfDirectory(int(sys.argv[1]))
    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha ao ler cache: {e}")
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

def list_tags_for_country(country_code, country_name):
    """Busca e lista as tags mais populares para um país específico."""
    if not country_code: return

    try:
        params = {
            'countrycode': country_code,
            'hidebroken': 'true',
            'limit': 150,
            'order': 'clickcount',
            'reverse': 'true'
        }
        r = requests.get(f"{API_URL}/search", params=params, timeout=15)
        r.raise_for_status()
        stations = r.json()

        if not stations:
            xbmcgui.Dialog().notification("Aviso", f"Nenhuma estação encontrada para {country_name}.")
            xbmcplugin.endOfDirectory(int(sys.argv[1]))
            return

        tag_counts = {}
        for station in stations:
            tags = station.get('tags', '').split(',')
            for tag in tags:
                tag = tag.strip().lower()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        sorted_tags = sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)

        for tag, count in sorted_tags:
            label = f"{tag.capitalize()} ({count} estações)"
            li = xbmcgui.ListItem(label=label)
            url = get_url(action='by_country_and_tag', country_code=country_code, tag=tag)
            xbmcplugin.addDirectoryItem(int(sys.argv[1]), url, li, isFolder=True)

        xbmcplugin.endOfDirectory(int(sys.argv[1]))
    except Exception as e:
        xbmcgui.Dialog().notification("Erro", f"Falha na API: {str(e)}")
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

def router(args):
    """Roteador de URL do plugin."""
    params = dict(urllib.parse.parse_qsl(args))
    action = params.get('action')
    
    if action == 'search':
        search_radio()
    elif action == 'custom':
        list_custom()
    elif action == 'list_countries':
        list_countries()
    elif action == 'update_cache':
        update_local_cache()
    elif action == 'country':
        fetch_stations({'country': params.get('country'), 'limit': 50})
    elif action == 'by_tag':
        fetch_stations({'tag': params.get('tag'), 'limit': 50})
    elif action == 'tags_by_country':
        list_tags_for_country(params.get('country_code'), params.get('country_name'))
    elif action == 'by_country_and_tag':
        fetch_stations({'countrycode': params.get('country_code'), 'tag': params.get('tag'), 'limit': 50})
    else:
        list_categories()

if __name__ == '__main__':
    # Remove o '?' inicial se existir
    args = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    router(args)