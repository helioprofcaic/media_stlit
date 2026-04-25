import sys
import os
import urllib.parse
import json
import re
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import requests
from bs4 import BeautifulSoup

# Configurações Globais
BASE_URL = "https://comandoplay.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import urllib.request
import ssl
import xbmcvfs

def get_html(url, referer=None):
    headers_dict = {
        'User-Agent': USER_AGENT,
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    if referer:
        headers_dict['Referer'] = referer
    
    try:
        response = requests.get(url, headers=headers_dict, timeout=15, verify=False)
        response.raise_for_status()
        return response.text
    except Exception as e:
        try:
            req = urllib.request.Request(url, headers=headers_dict)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception as fallback_e:
            try:
                # Fallback 3: Motor nativo do Kodi (C++ libcurl). Imparável no Android.
                headers_str = f"User-Agent={urllib.parse.quote(USER_AGENT)}"
                if referer:
                    headers_str += f"&Referer={urllib.parse.quote(referer)}"
                
                v_url = f"{url}|{headers_str}"
                f = xbmcvfs.File(v_url)
                resp = f.read()
                f.close()
                if resp:
                    return resp.decode('utf-8', errors='ignore')
                else:
                    raise Exception("VFS Empty")
            except Exception as vfs_e:
                try:
                    # Fallback 4: Usar um proxy público (AllOrigins) para driblar o bloqueio de provedor.
                    import json
                    proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
                    proxy_req = urllib.request.Request(proxy_url, headers={'User-Agent': USER_AGENT})
                    ctx2 = ssl.create_default_context()
                    ctx2.check_hostname = False
                    ctx2.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(proxy_req, context=ctx2, timeout=20) as resp:
                        data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                        if data and 'contents' in data:
                            return data['contents']
                        else:
                            raise Exception("Proxy Empty")
                except Exception as proxy_e:
                    error_msg = f"Rede bloqueada. Mude o DNS da Box para 1.1.1.1 ou 8.8.8.8"
                    xbmc.log(f"ComandoPlay Error: Bloqueio Total | V:{vfs_e} P:{proxy_e}", xbmc.LOGERROR)
                    xbmcgui.Dialog().notification('Bloqueio Operadora', error_msg, xbmcgui.NOTIFICATION_ERROR, 8000)
                    return None

def list_main_menu():
    """Menu Principal."""
    categories = [
        ("Início / Destaques", f"{BASE_URL}/"),
        ("Filmes", f"{BASE_URL}/category/movies/"),
        ("Séries", f"{BASE_URL}/category/tv-series/"),
        ("Ação", f"{BASE_URL}/category/acao/"),
        ("Comédia", f"{BASE_URL}/category/comedia/"),
    ]
    
    for label, url in categories:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': 'DefaultFolder.png'})
        url_params = urllib.parse.urlencode({'action': 'list_content', 'url': url})
        plugin_url = f"{sys.argv[0]}?{url_params}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=plugin_url, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_content(url):
    """Lista filmes e séries de uma página."""
    html = get_html(url)
    if not html:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    items_found = False
    
    # Busca por articles/li/div com posters no ComandoPlay
    articles = soup.find_all(['article', 'li', 'div'], id=re.compile(r'^post-'))
    for article in articles:
        link_tag = article.find('a', href=True)
        if not link_tag:
            continue
            
        href = link_tag['href']
        title_tag = article.find(['h2', 'h3', 'div'], class_=re.compile(r'title|name'))
        title = title_tag.text.strip() if title_tag else link_tag.get('title')
        if not title:
            # Fallback para o alt da imagem
            img = article.find('img')
            if img and img.get('alt'):
                title = img.get('alt').strip()
            else:
                continue

        img_tag = article.find('img')
        thumbnail = ""
        if img_tag:
            thumbnail = img_tag.get('data-src') or img_tag.get('src') or ""
        
        li = xbmcgui.ListItem(label=title)
        li.setArt({'thumb': thumbnail, 'icon': thumbnail, 'fanart': thumbnail})
        li.setInfo('video', {'title': title, 'mediatype': 'video'})
        
        # Agora manda para 'list_servers' em vez de play direto, passando o título para memória
        url_params = urllib.parse.urlencode({'action': 'list_servers', 'url': href, 'title': title})
        plugin_url = f"{sys.argv[0]}?{url_params}"
        
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=plugin_url, listitem=li, isFolder=True)
        items_found = True

    if not items_found:
        xbmcgui.Dialog().notification('Aviso', 'Nenhum vídeo encontrado nesta categoria.', xbmcgui.NOTIFICATION_WARNING)

    # Paginação se existir
    next_page = soup.find('a', class_=re.compile(r'next'), href=True)
    if next_page:
        li = xbmcgui.ListItem(label="Próxima Página >>")
        url_params = urllib.parse.urlencode({'action': 'list_content', 'url': next_page['href']})
        plugin_url = f"{sys.argv[0]}?{url_params}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=plugin_url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE)

def list_servers(movie_url, movie_title_fallback="Vídeo"):
    """Lista todos os servidores disponíveis para um filme."""
    html = get_html(movie_url)
    if not html:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    soup = BeautifulSoup(html, 'html.parser')
    servers = []

    # 1. Busca links diretos (padrão principal)
    # Procura por links que contenham domínios de players conhecidos
    providers = [
        ('BRStream (Principal)', r'watch\.brstream\.cc'),
        ('EmbedPlay', r'embedplay\.icu'),
        ('SeekPlays', r'seekplays\.online'),
        ('Voe', r'voe\.sx'),
        ('StreamWish', r'streamwish\.com'),
    ]

    links = soup.find_all('a', href=True)
    for label_base, pattern in providers:
        for a in links:
            href = a['href']
            if re.search(pattern, href):
                # Tenta pegar um rótulo melhor se disponível (ex: Opção 1, Dublado, etc)
                text = a.text.strip()
                if not text or len(text) > 30:
                    text = label_base
                
                servers.append({
                    'label': text,
                    'url': href,
                    'icon': 'DefaultVideo.png'
                })

    if not servers:
        # Fallback: procura qualquer link que pareça um player se nada foi achado
        for a in links:
            href = a['href']
            if '/watch/' in href or '/v/' in href or '/embed/' in href:
                if any(ext in href for ext in ['brstream', 'player', 'video']):
                    servers.append({
                        'label': 'Servidor Alternativo',
                        'url': href,
                        'icon': 'DefaultVideo.png'
                    })

    # Remove duplicatas mantendo a ordem
    seen = set()
    unique_servers = []
    for s in servers:
        if s['url'] not in seen:
            seen.add(s['url'])
            unique_servers.append(s)

    # Tenta pegar o título do filme da página ou usa o que veio da navegação (memória)
    h1 = soup.find('h1')
    movie_title = h1.text.strip() if h1 else movie_title_fallback

    for s in unique_servers:
        li = xbmcgui.ListItem(label=s['label'])
        li.setArt({'icon': s['icon']})
        li.setInfo('video', {'title': movie_title})
        li.setProperty('IsPlayable', 'true')
        
        url_params = urllib.parse.urlencode({
            'action': 'play_server', 
            'url': s['url'],
            'referer': movie_url,
            'title': movie_title
        })
        plugin_url = f"{sys.argv[0]}?{url_params}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=plugin_url, listitem=li, isFolder=False)

    if not unique_servers:
        xbmcgui.Dialog().notification('Erro', 'Nenhum servidor encontrado para este filme.', xbmcgui.NOTIFICATION_ERROR)

    xbmcplugin.endOfDirectory(HANDLE)

def play_server(server_url, referer_url, title="Vídeo"):
    """Resolve e reproduz um servidor específico."""
    final_stream = None
    
    # Se for BRStream, resolve o HLS
    if 'brstream.cc' in server_url:
        br_html = get_html(server_url, referer=referer_url)
        if br_html:
            video_json_match = re.search(r'var video = ({.*?});', br_html)
            if video_json_match:
                try:
                    v_data = json.loads(video_json_match.group(1))
                    uid = v_data.get('uid')
                    md5 = v_data.get('md5')
                    vid = v_data.get('id')
                    status = v_data.get('status')
                    
                    if not uid or not vid:
                         pass

                    # Constrói o link do master
                    # Se o md5 for nulo, tenta a URL simplificada
                    if md5:
                        base_stream = f"https://watch.brstream.cc/m3u8/{uid}/{md5}/master.m3u8"
                    else:
                        base_stream = f"https://watch.brstream.cc/m3u8/{uid}/{vid}/master.m3u8"

                    headers_encoded = urllib.parse.urlencode({
                        'User-Agent': USER_AGENT,
                        'Referer': "https://watch.brstream.cc/"
                    })
                    final_stream = f"{base_stream}?s=1&id={vid}&cache={status}|{headers_encoded}"
                except:
                    pass
    
    # Suporte básico para EmbedPlay.icu (geralmente redireciona para BRStream)
    elif 'embedplay.icu' in server_url:
        icu_html = get_html(server_url, referer=referer_url)
        if icu_html:
            br_match = re.search(r'playVideo\([\'"](https?://(?:watch\.)?brstream\.cc/[^\'"]+)[\'"]', icu_html)
            if br_match:
                return play_server(br_match.group(1), server_url, title)

    if final_stream:
        li = xbmcgui.ListItem(path=final_stream)
        li.setInfo('video', {'title': title})
        li.setProperty('inputstream', 'inputstream.adaptive')
        li.setProperty('inputstream.adaptive.manifest_type', 'hls')
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
    else:
        # Tenta tocar a URL diretamente se não tiver lógica específica (muitos players aceitam)
        li = xbmcgui.ListItem(path=server_url)
        li.setInfo('video', {'title': title})
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)

def router(param_string):
    params = urllib.parse.parse_qs(param_string)
    action = params.get('action', [None])[0]
    url = params.get('url', [None])[0]

    if action == 'list_content' and url:
        list_content(url)
    elif action == 'list_servers' and url:
        title = params.get('title', ["Vídeo"])[0]
        list_servers(url, title)
    elif action == 'play_server' and url:
        referer = params.get('referer', [None])[0]
        title = params.get('title', ["Vídeo"])[0]
        play_server(url, referer, title)
    else:
        list_main_menu()

if __name__ == '__main__':
    if len(sys.argv) > 2:
        router(sys.argv[2][1:])
    else:
        router("")
