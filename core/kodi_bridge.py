import sys
import os
import importlib.util
import xml.etree.ElementTree as ET
import shutil
import json
import threading
import re
import warnings
from core.utils import ADDONS_DIR, DATA_DIR, PLUGINS_REPO_DIR

# Armazenamento local para thread (suporte a multiusuário no Streamlit)
_local = threading.local()

# Lock global para garantir execução atômica de plugins (protege sys.argv e sys.modules)
_plugin_lock = threading.Lock()

class DialogSelectError(Exception):
    """Exceção lançada quando o plugin solicita uma seleção do usuário."""
    def __init__(self, heading, options):
        self.heading = heading
        self.options = options

class DialogInputError(Exception):
    """Exceção lançada quando o plugin solicita texto do usuário."""
    def __init__(self, heading, default):
        self.heading = heading
        self.default = default

def get_bridge_data():
    if not hasattr(_local, 'data'):
        _local.data = {
            "items": [],
            "resolved_url": None,
            "drm_info": None,
            "media_info": {}
        }
    if _local.data.get("media_info") is None:
        _local.data["media_info"] = {}
    return _local.data

def get_window_props():
    if not hasattr(_local, 'window_props'):
        _local.window_props = {}
    return _local.window_props

# Callback global para atualizações de metadados em tempo real
_metadata_callback = None

def register_metadata_callback(callback):
    global _metadata_callback
    _metadata_callback = callback

def get_playlists():
    if not hasattr(_local, 'playlists'):
        _local.playlists = {0: [], 1: []} # 0: Music, 1: Video
    return _local.playlists

# --- Classes que simulam a API do Kodi ---

class MockListItem:
    def __init__(self, label="", path="", offscreen=False, **kwargs):
        self.label = label
        self.path = path
        self.art = {}
        self.info = {}
        self.properties = {}
        self.context_menu = []
        self.media_type = 'video'

    def setArt(self, art):
        self.art.update(art)

    def setInfo(self, type, infoLabels):
        self.info.update(infoLabels)
        self.media_type = type

    def setProperty(self, key, value):
        self.properties[key] = value

    def addContextMenuItems(self, items):
        self.context_menu.extend(items)
    
    def getLabel(self):
        if isinstance(self.label, bytes):
            return self.label.decode('utf-8', errors='ignore')
        return str(self.label) if self.label is not None else ""

    def getPath(self):
        if isinstance(self.path, bytes):
            return self.path.decode('utf-8', errors='ignore')
        return str(self.path) if self.path is not None else ""

    def setPath(self, path):
        self.path = path

    def getProperty(self, key):
        return self.properties.get(key, "")

class MockXBMC:
    LOGDEBUG, LOGINFO, LOGNOTICE, LOGWARNING, LOGERROR, LOGFATAL, LOGNONE = range(7)
    PLAYLIST_VIDEO = 1
    PLAYLIST_MUSIC = 0
    ENGLISH_NAME = 2
    ISO_639_1 = 1
    ISO_639_2 = 2
    
    @staticmethod
    def log(msg, level=LOGNOTICE):
        print(f"[KODI LOG] {msg}")

    @staticmethod
    def executebuiltin(function):
        print(f"[KODI EXEC] {function}")

    @staticmethod
    def executeJSONRPC(json_rpc):
        # Simulação básica para evitar crashes em plugins que buscam info do addon
        try:
            req = json.loads(json_rpc)
            if "Addons.GetAddonDetails" in req.get("method", ""):
                return json.dumps({
                    "result": {
                        "addon": {
                            "addonid": req.get("params", {}).get("addonid", "unknown"),
                            "version": "1.0.0",
                            "enabled": True
                        }
                    }
                })
        except:
            pass
        return '{"result": {"value": "ok"}}'

    @staticmethod
    def getSkinDir():
        return "skin.estuary"

    @staticmethod
    def getLanguage(format=0):
        # Retorna Português para compatibilidade com plugins BR (BrazucaPlay)
        if format == MockXBMC.ISO_639_1:
            return "pt"
        if format == MockXBMC.ISO_639_2:
            return "por"
        return "Portuguese (Brazil)"

    @staticmethod
    def convertLanguage(language, format):
        return language

    @staticmethod
    def getSupportedMedia(mediaType):
        return ".mp4|.mkv|.avi|.mov|.wmv|.flv|.webm|.mp3|.wav|.m4v|.ts|.m3u8"

    @staticmethod
    def sleep(time):
        import time as t
        t.sleep(time / 1000.0)

    @staticmethod
    def getCondVisibility(condition):
        if 'inputstream.adaptive' in condition:
            return True
        if 'System.Platform.Android' in condition:
            return False
        if 'System.HasAddon' in condition:
            # Tenta extrair o ID do addon: System.HasAddon(id)
            match = re.search(r'System\.HasAddon\(([^)]+)\)', condition)
            if match:
                addon_id = match.group(1)
                # Retorna True se estiver nos mocks ou instalado
                if addon_id in sys.modules or os.path.exists(os.path.join(ADDONS_DIR, addon_id)):
                    return True
            return True # Assume true por segurança
        return False

    @staticmethod
    def getInfoLabel(info):
        info_lower = info.lower()
        if info_lower == 'system.buildversion':
            return "19.0"
            
        # Retorna "0" para chaves que parecem numéricas para evitar crashes de int("")
        # Expandido para incluir mais casos comuns em plugins complexos
        if any(x in info_lower for x in ['duration', 'count', 'time', 'year', 'number', 'index', 'dbid', 'season', 'episode', 'view', 'system', 'container', 'playlist', 'id', 'position', 'total', 'progress']):
            return "0"
            
        # Se for chave de texto conhecida, retorna vazio sem aviso
        if any(x in info_lower for x in ['label', 'title', 'plot', 'path', 'icon', 'thumb', 'art', 'genre', 'studio', 'country', 'premiered', 'name']):
            return ""
            
        print(f"[WARNING] getInfoLabel('{info}') desconhecido. Retornando '0'.")
        return "0"

    @staticmethod
    def getUserAgent():
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    @staticmethod
    def getRegion(id):
        return "BR"

    class Keyboard:
        def __init__(self, default='', heading='', hidden=False):
            self.text = default
            self.heading = heading
        def doModal(self):
            # Em uma implementação real, abriríamos um QDialog aqui.
            # Por enquanto, simulamos uma busca fixa para teste se necessário.
            pass
        def isConfirmed(self):
            return True
        def getText(self):
            # Retorna um termo de busca padrão se o plugin pedir input
            return "amador"
            
    @staticmethod
    def translatePath(path):
        return MockXBMCVFS.translatePath(path)

    class Monitor:
        def __init__(self, *args, **kwargs):
            pass
        def onSettingsChanged(self):
            pass
        def onNotification(self, sender, method, data):
            pass
        def waitForAbort(self, timeout=-1):
            return False
        def abortRequested(self):
            return False

    class Player:
        def __init__(self):
            pass
        def play(self, item='', listitem=None, windowed=False, startpos=-1):
            print(f"[KODI PLAYER] Play: {item}")
            
            target_url = item
            target_listitem = listitem
            
            # Suporte a reprodução de Playlist (objeto ou ID)
            if isinstance(item, MockXBMC.PlayList):
                item = item.id
            elif hasattr(item, 'id') and hasattr(item, 'add'): # Fallback para reload de classes
                item = item.id
            
            if isinstance(item, int):
                playlists = get_playlists()
                if item in playlists and playlists[item]:
                    # Pega o item na posição startpos ou 0
                    idx = startpos if startpos >= 0 else 0
                    if idx < len(playlists[item]):
                        entry = playlists[item][idx]
                        target_url = entry['url']
                        target_listitem = entry['listitem'] or target_listitem
                        print(f"[KODI PLAYER] Resolvido da Playlist ({item}): {target_url}")

            # Salva a URL para o VideoPlayer pegar via bridge_data
            data = get_bridge_data()
            data["resolved_url"] = str(target_url) if target_url is not None else ""
            
            if target_listitem:
                info = getattr(target_listitem, 'info', {}).copy()
                art = getattr(target_listitem, 'art', {}).copy()
                if 'title' not in info:
                    info['title'] = target_listitem.getLabel()
                
                data["media_info"] = {
                    "title": info.get('title'),
                    "artist": info.get('artist'),
                    "plot": info.get('plot'),
                    "icon": art.get('icon') or art.get('thumb'),
                    "type": getattr(target_listitem, 'media_type', 'video')
                }

        def stop(self):
            # Em um player real, pararia a reprodução. Aqui apenas limpamos o estado se necessário.
            pass

        def isPlaying(self): 
            return get_bridge_data()["resolved_url"] is not None
            
        def isPlayingVideo(self): return False
        def isPlayingAudio(self): return True
        def pause(self): pass
        def seekTime(self, time): pass
        def getTime(self): return 0
        def getTotalTime(self): return 0
        
        def getPlayingFile(self):
            return get_bridge_data()["resolved_url"] or ""
            
        def updateInfoTag(self, listitem):
            # Captura metadados e envia para o player via callback
            info = listitem.info if hasattr(listitem, 'info') else {}
            art = listitem.art if hasattr(listitem, 'art') else {}
            
            # Mescla info e art para enviar tudo junto
            data = info.copy()
            data.update(art)
            
            print(f"[KODI PLAYER] UpdateInfoTag: {data}")
            
            global _metadata_callback
            if _metadata_callback:
                try:
                    _metadata_callback(data)
                except:
                    pass

    class PlayList:
        def __init__(self, playlist):
            self.id = playlist
        def clear(self):
            get_playlists()[self.id] = []
        def add(self, url, listitem=None, index=-1):
            # Armazena o item na playlist correta
            get_playlists()[self.id].append({'url': url, 'listitem': listitem})
        def size(self):
            return len(get_playlists().get(self.id, []))
        def getposition(self): return 0

    class Actor:
        def __init__(self, name, role, thumbnail, **kwargs):
            pass

class MockXBMCGUI:
    ListItem = MockListItem
    NOTIFICATION_INFO = 'info'
    NOTIFICATION_WARNING = 'warning'
    NOTIFICATION_ERROR = 'error'
    INPUT_NUMERIC = 0
    INPUT_ALPHANUM = 1

    @staticmethod
    def getCurrentWindowId():
        return 10000

    @staticmethod
    def getCurrentWindowDialogId():
        return 9999

    class Dialog:
        def notification(self, heading, message, icon=None, time=5000, sound=True):
            print(f"[NOTIFICATION] {heading}: {message}")

        def yesno(self, heading, line1, line2="", line3="", nolabel="No", yeslabel="Yes"):
            print(f"[DIALOG YESNO] {heading}: {line1} {line2} {line3}")
            return True

        def ok(self, heading, line1, line2="", line3=""):
            print(f"[DIALOG OK] {heading}: {line1} {line2} {line3}")
            return True

        def select(self, heading, list):
            print(f"[DIALOG SELECT] {heading}")
            if hasattr(_local, 'dialog_answers') and _local.dialog_answers:
                return _local.dialog_answers.pop(0)
            if list:
                raise DialogSelectError(heading, list)
            return -1

        def input(self, heading, default="", type=1, option=0, password=False):
            print(f"[DIALOG INPUT] {heading}")
            if hasattr(_local, 'dialog_answers') and _local.dialog_answers:
                return _local.dialog_answers.pop(0)
            # Interrompe para pedir input ao usuário
            raise DialogInputError(heading, default)
            
    class DialogProgress:
        def create(self, heading, message=""): pass
        def update(self, percent, line1="", line2="", line3=""): pass
        def close(self): pass
        def iscanceled(self): return False

    class DialogProgressBG:
        def create(self, heading, message=""): pass
        def update(self, percent, heading="", message=""): pass
        def close(self): pass
        def isFinished(self): return True

    class Window:
        def __init__(self, windowId):
            self.id = windowId
        def getProperty(self, key):
            props = get_window_props()
            val = props.get(f"{self.id}_{key}", "")
            if not val:
                 # Heurística defensiva: se não tem valor e não parece texto, retorna "0"
                 key_lower = key.lower()
                 if not any(x in key_lower for x in ['name', 'label', 'title', 'path', 'icon', 'thumb', 'art']):
                     return "0"
            return val
        def setProperty(self, key, value):
            props = get_window_props()
            props[f"{self.id}_{key}"] = str(value)
        def clearProperty(self, key):
            props = get_window_props()
            k = f"{self.id}_{key}"
            if k in props:
                del props[k]
        def getFocusId(self): return 0
        def getControl(self, id): return None

    class WindowXMLDialog(Window):
        def __init__(self, xmlFilename, scriptPath, defaultSkin='Default', forceFallback='Default'):
            pass
        def doModal(self): pass
        def close(self): pass

class MockXBMCPlugin:
    # Constantes de Ordenação (Sort Methods)
    SORT_METHOD_NONE = 0
    SORT_METHOD_LABEL = 1
    SORT_METHOD_LABEL_IGNORE_THE = 2
    SORT_METHOD_DATE = 3
    SORT_METHOD_SIZE = 4
    SORT_METHOD_FILE = 5
    SORT_METHOD_DRIVE_TYPE = 6
    SORT_METHOD_TRACKNUM = 7
    SORT_METHOD_DURATION = 8
    SORT_METHOD_TITLE = 9
    SORT_METHOD_TITLE_IGNORE_THE = 10
    SORT_METHOD_ARTIST = 11
    SORT_METHOD_ARTIST_IGNORE_THE = 12
    SORT_METHOD_ALBUM = 13
    SORT_METHOD_ALBUM_IGNORE_THE = 40
    SORT_METHOD_GENRE = 14
    SORT_METHOD_COUNTRY = 15
    SORT_METHOD_YEAR = 16
    SORT_METHOD_VIDEO_YEAR = 16
    SORT_METHOD_VIDEO_RATING = 17
    SORT_METHOD_VIDEO_USER_RATING = 18
    SORT_METHOD_DATE_ADDED = 19
    SORT_METHOD_DATEADDED = 19
    SORT_METHOD_PROGRAM_COUNT = 20
    SORT_METHOD_PLAYLIST_ORDER = 21
    SORT_METHOD_EPISODE = 22
    SORT_METHOD_VIDEO_TITLE = 23
    SORT_METHOD_SORT_TITLE = 24
    SORT_METHOD_VIDEO_SORT_TITLE = 24
    SORT_METHOD_VIDEO_SORT_TITLE_IGNORE_THE = 25
    SORT_METHOD_PRODUCTIONCODE = 25
    SORT_METHOD_SONG_RATING = 26
    SORT_METHOD_MPAA_RATING = 27
    SORT_METHOD_VIDEO_RUNTIME = 28
    SORT_METHOD_STUDIO = 29
    SORT_METHOD_STUDIO_IGNORE_THE = 30
    SORT_METHOD_UNSORTED = 31
    SORT_METHOD_BITRATE = 32
    SORT_METHOD_LISTENERS = 33
    SORT_METHOD_FULLPATH = 34
    SORT_METHOD_LABEL_IGNORE_FOLDERS = 35
    SORT_METHOD_LASTPLAYED = 36
    SORT_METHOD_PLAYCOUNT = 37
    SORT_METHOD_CHANNEL = 38
    SORT_METHOD_DATE_TAKEN = 39
    SORT_METHOD_GAME_TYPE = 41
    
    SORT_ORDER_NONE = 0
    SORT_ORDER_ASC = 1
    SORT_ORDER_DESC = 2

    @staticmethod
    def addDirectoryItem(handle, url, listitem, isFolder=False, totalItems=0):
        # Captura o item que o plugin quer mostrar na tela
        if isinstance(url, bytes):
            url = url.decode('utf-8', errors='ignore')
            
        get_bridge_data()["items"].append({
            'url': url,
            'label': listitem.getLabel(),
            'art': listitem.art,
            'isFolder': isFolder,
            'listitem': listitem
        })
        return True

    @staticmethod
    def addDirectoryItems(handle, items, totalItems=0):
        # items é uma lista de tuplas (url, listitem, isFolder)
        for url, listitem, isFolder in items:
            MockXBMCPlugin.addDirectoryItem(handle, url, listitem, isFolder, totalItems)
        return True

    @staticmethod
    def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
        pass

    @staticmethod
    def setResolvedUrl(handle, succeeded, listitem):
        path = listitem.getPath()
        data = get_bridge_data()
        
        # Adaptação para inputstream.adaptive no Media-HL
        # Transfere headers definidos nas propriedades para a URL (formato pipe)
        if listitem.properties.get('inputstream') == 'inputstream.adaptive':
            headers = listitem.properties.get('inputstream.adaptive.stream_headers') or \
                      listitem.properties.get('inputstream.adaptive.manifest_headers')
            if headers and "|" not in path:
                path = f"{path}|{headers}"
        
            # Captura informações de DRM (Widevine) definidas pelo plugin
            license_key = listitem.properties.get('inputstream.adaptive.license_key')
            if license_key:
                data["drm_info"] = {
                    "key": license_key,
                    "type": listitem.properties.get('inputstream.adaptive.license_type', 'com.widevine.alpha')
                }

        # Captura metadados para exibição no player
        info = getattr(listitem, 'info', {}).copy()
        art = getattr(listitem, 'art', {}).copy()
        if 'title' not in info:
            info['title'] = listitem.getLabel()
            
        data["media_info"] = {
            "title": info.get('title'),
            "artist": info.get('artist'),
            "plot": info.get('plot'),
            "icon": art.get('icon') or art.get('thumb'),
            "type": getattr(listitem, 'media_type', 'video')
        }

        data["resolved_url"] = path

    @staticmethod
    def setContent(handle, content):
        pass

    @staticmethod
    def setPluginCategory(handle, category):
        pass

    @staticmethod
    def addSortMethod(handle, sortMethod, label2Mask=""):
        pass

class MockXBMCVFS:
    @staticmethod
    def exists(path):
        return os.path.exists(path)

    @staticmethod
    def mkdir(path):
        try:
            os.mkdir(path)
            return True
        except:
            return False

    @staticmethod
    def mkdirs(path):
        try:
            os.makedirs(path)
            return True
        except:
            return False

    @staticmethod
    def translatePath(path):
        # Normaliza barras
        path = path.replace("\\", "/")
        
        if path.startswith("special://home/addons/"):
            # Tenta resolver para o caminho real do addon (instalado ou dev)
            rel_path = path.replace("special://home/addons/", "")
            parts = rel_path.split("/")
            addon_id = parts[0]
            
            # Verifica onde o addon está instalado
            candidate_1 = os.path.join(ADDONS_DIR, addon_id)
            candidate_2 = os.path.join(PLUGINS_REPO_DIR, addon_id)
            
            base = candidate_1
            if os.path.exists(candidate_2):
                base = candidate_2
            
            if len(parts) > 1:
                path = os.path.join(base, *parts[1:])
            else:
                path = base
                
        elif path.startswith("special://home"):
             path = path.replace("special://home", DATA_DIR)
        elif path.startswith("special://profile"):
             path = path.replace("special://profile", os.path.join(DATA_DIR, "userdata"))
        elif path.startswith("special://temp"):
             path = path.replace("special://temp", os.path.join(DATA_DIR, "temp"))
        elif path.startswith("special://"):
             path = path.replace("special://", os.path.join(DATA_DIR, ""))
        
        # Hack para plugins que esperam bytes e chamam .decode() em strings
        class DecodableString(str):
            def decode(self, encoding="utf-8", errors="strict"):
                return self
        return DecodableString(path)

    @staticmethod
    def delete(path):
        try:
            os.remove(path)
            return True
        except:
            return False

    @staticmethod
    def copy(source, destination):
        try:
            shutil.copy2(source, destination)
            return True
        except:
            return False

    @staticmethod
    def rename(file, newFileName):
        try:
            os.rename(file, newFileName)
            return True
        except:
            return False

    @staticmethod
    def rmdir(path, force=False):
        try:
            if force:
                shutil.rmtree(path)
            else:
                os.rmdir(path)
            return True
        except:
            return False

    @staticmethod
    def listdir(path):
        dirs, files = [], []
        try:
            for name in os.listdir(path):
                (dirs if os.path.isdir(os.path.join(path, name)) else files).append(name)
        except: pass
        return dirs, files

    class File:
        def __init__(self, path, mode='r'):
            self.path = path
        def write(self, data): pass
        def read(self): return ""
        def close(self): pass

    class Stat:
        def __init__(self, path):
            self.path = path
        
        def st_size(self):
            try:
                return os.path.getsize(self.path)
            except:
                return 0
        
        def st_mtime(self):
            try:
                return os.path.getmtime(self.path)
            except:
                return 0

class MockListItemInfoTag:
    def __init__(self, listitem, media_type='video', tag_type=None, **kwargs):
        self.listitem = listitem
        self.media_type = tag_type if tag_type else media_type
    
    def set_info(self, info_labels):
        self.listitem.setInfo(self.media_type, info_labels)

class MockLocalizedString(str):
    """String que aceita formatação (%) mesmo que não tenha placeholders, para evitar crashes."""
    def __mod__(self, other):
        try:
            return super().__mod__(other)
        except (TypeError, ValueError):
            # Se sobrar argumentos ou faltar placeholders, apenas concatena
            return f"{self} {other}"
    def decode(self, encoding="utf-8", errors="strict"):
        return self

class MockInputStreamHelper:
    class Helper:
        def __init__(self, protocol, drm=None):
            pass
        def check_inputstream(self):
            return True
        def inputstream_addon(self):
            return 'inputstream.adaptive'

class MockRouting:
    class Plugin:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def route(self, path_pattern):
            def decorator(func):
                # Transforma padrão de rota do plugin em Regex
                # Ex: '/play/<video_id>' -> '^/play/(?P<video_id>[^/]+)$'
                pattern = path_pattern
                if not pattern.startswith('^'):
                    regex = "^"
                    parts = pattern.split('/')
                    for part in parts:
                        if not part: continue
                        regex += "/"
                        if part.startswith('<') and part.endswith('>'):
                            name = part[1:-1]
                            if ':' in name: name = name.split(':')[0] # Remove tipo ex: <int:id>
                            regex += f"(?P<{name}>[^/]+)"
                        else:
                            regex += re.escape(part)
                    regex += "$"
                    if pattern == "/": regex = "^/$"
                else:
                    regex = pattern
                
                self.routes.append((regex, func))
                return func
            return decorator

        def run(self):
            # Reconstrói o caminho a partir do sys.argv
            full_url = sys.argv[0]
            if len(sys.argv) > 2:
                full_url += sys.argv[2]
            
            path = "/"
            if "://" in full_url:
                try:
                    # Remove protocolo e ID do addon: plugin://plugin.video.exemplo/foo/bar -> /foo/bar
                    rest = full_url.split("://", 1)[1]
                    if "/" in rest:
                        path = "/" + rest.split("/", 1)[1]
                        # Remove query string do path para matching
                        if "?" in path:
                            path = path.split("?", 1)[0]
                    else:
                        path = "/"
                except:
                    path = "/"
            
            # Tenta casar com as rotas registradas
            for pattern, func in self.routes:
                match = re.match(pattern, path)
                if match:
                    kwargs = match.groupdict()
                    try:
                        func(**kwargs)
                    except TypeError:
                        # Fallback caso a função não aceite argumentos nomeados
                        func()
                    return
            
            print(f"[MockRouting] 404 Not Found: {path}")

class MockResolveURL:
    @staticmethod
    def resolve(url):
        return url
    
    class HostedMediaFile:
        def __init__(self, url, **kwargs):
            self.url = url
        def resolve(self):
            return self.url

class MockMetaHandler:
    class metahandlers:
        class MetaData:
            def __init__(self, preparezip=False):
                pass
            def get_meta(self, media_type, name, **kwargs):
                return {}
            def get_episode_meta(self, *args, **kwargs):
                return {}

class MockXBMCAddon:
    class Addon:
        def __init__(self, id=None):
            self.id = id
            if not self.id:
                # Tenta deduzir o ID do addon pelo sys.argv (URL do plugin)
                if len(sys.argv) > 0 and sys.argv[0].startswith("plugin://"):
                    self.id = sys.argv[0].replace("plugin://", "").strip("/")
                else:
                    self.id = "unknown"
            
            # Configura caminho de persistência de configurações
            self.profile_path = os.path.join(DATA_DIR, "userdata", "addon_data", self.id)
            self.settings_file = os.path.join(self.profile_path, "settings.json")
            self._settings = {}
            self._load_settings()

        def _load_settings(self):
            if os.path.exists(self.settings_file):
                try:
                    with open(self.settings_file, 'r', encoding='utf-8') as f:
                        self._settings = json.load(f)
                except:
                    pass

        def _save_settings(self):
            try:
                if not os.path.exists(self.profile_path):
                    os.makedirs(self.profile_path)
                with open(self.settings_file, 'w', encoding='utf-8') as f:
                    json.dump(self._settings, f, indent=4)
            except:
                pass

        def getAddonInfo(self, id):
            if id == 'profile':
                if not os.path.exists(self.profile_path):
                    os.makedirs(self.profile_path)
                
                # Garante que a pasta databases exista (necessário para plugins como FEN)
                db_path = os.path.join(self.profile_path, "databases")
                if not os.path.exists(db_path):
                    os.makedirs(db_path)
                    
                return self.profile_path
            if id == 'id': return self.id
            if id == 'name': return self.id
            if id == 'path': return MockXBMCVFS.translatePath(f"special://home/addons/{self.id}")
            if id == 'version': return "1.0.0"
            if id == 'icon': 
                # Tenta encontrar o ícone na pasta de addons instalados
                icon_path = os.path.join(ADDONS_DIR, self.id, "icon.png")
                if os.path.exists(icon_path): return icon_path
                
                # Tenta encontrar na pasta de plugins locais (Dev)
                icon_path = os.path.join(PLUGINS_REPO_DIR, self.id, "icon.png")
                if os.path.exists(icon_path): return icon_path
                
                return os.path.join(ADDONS_DIR, self.id, "icon.png")
            return ''
        
        def getSetting(self, id):
            if id in self._settings:
                return str(self._settings[id])

            # Retorna valores padrão seguros para evitar erros de conversão (int/bool)
            if 'port' in id: return "8080"
            if 'whitelist' in id: return "false"
            if 'mpd' in id: return "false"
            
            # Heurística: se o nome da configuração sugere número, retorna valor seguro
            # Evita erro: invalid literal for int() with base 10: ''
            id_lower = id.lower()
            
            if 'timeout' in id_lower:
                return "60"
            
            if any(x in id_lower for x in ['cache', 'buffer']):
                return "100"

            if any(x in id_lower for x in ['limit', 'count', 'items', 'page', 'time', 'duration', 'width', 'height', 'cache', 'buffer', 'port', 'num', 'max', 'min', 'size', 'interval', 'timeout', 'level', 'bitrate', 'view', 'mode', 'depth', 'current', 'total', 'progress']):
                return "10"
            
            if any(x in id_lower for x in ['enable', 'show', 'use', 'hide', 'active', 'auto']):
                return "true"
            
            # Silencia warnings para configurações comuns de plugins BR
            if any(x in id_lower for x in ['opt', 'extra', 'layout', 'pass', 'favoritos', 'epg', 'pais']):
                return "0"

            print(f"[WARNING] getSetting('{id}') não encontrado. Retornando '0' como padrão para evitar crash.")
            return "0" # Default genérico para evitar int('')
            
        def setSetting(self, id, value):
            self._settings[id] = value
            self._save_settings()

        def getLocalizedString(self, id): return MockLocalizedString(str(id))

# --- Função Principal da Ponte ---

def setup_mocks():
    """Injeta os módulos falsos no sistema para o plugin importar."""
    # Atualiza sempre os módulos para evitar incompatibilidade de classes (reload do Streamlit)
    sys.modules['xbmc'] = MockXBMC
    sys.modules['xbmcgui'] = MockXBMCGUI
    sys.modules['xbmcplugin'] = MockXBMCPlugin
    sys.modules['xbmcaddon'] = MockXBMCAddon
    sys.modules['xbmcvfs'] = MockXBMCVFS

    # Atualiza kodi_six
    kodi_six = sys.modules.get('kodi_six', type(sys)('kodi_six'))
    kodi_six.xbmc = MockXBMC
    kodi_six.xbmcgui = MockXBMCGUI
    kodi_six.xbmcplugin = MockXBMCPlugin
    kodi_six.xbmcaddon = MockXBMCAddon
    kodi_six.xbmcvfs = MockXBMCVFS
    sys.modules['kodi_six'] = kodi_six

    if 'infotagger' not in sys.modules:
        infotagger = type(sys)('infotagger')
        infotagger_listitem = type(sys)('infotagger.listitem')
        infotagger_listitem.ListItemInfoTag = MockListItemInfoTag
        infotagger.listitem = infotagger_listitem
        sys.modules['infotagger'] = infotagger
        sys.modules['infotagger.listitem'] = infotagger_listitem

    if 'inputstreamhelper' not in sys.modules:
        sys.modules['inputstreamhelper'] = MockInputStreamHelper

    if 'simplejson' not in sys.modules:
        sys.modules['simplejson'] = json
        
    if 'routing' not in sys.modules:
        sys.modules['routing'] = MockRouting

    if 'resolveurl' not in sys.modules:
        sys.modules['resolveurl'] = MockResolveURL
        
    if 'urlresolver' not in sys.modules:
        sys.modules['urlresolver'] = MockResolveURL
        
    if 'metahandler' not in sys.modules:
        sys.modules['metahandler'] = MockMetaHandler

def run_plugin(plugin_path, param_string="", dialog_answers=None):
    """Executa o plugin e retorna os itens ou a URL resolvida."""
    with _plugin_lock:
        setup_mocks()
        
        # Injeta respostas de diálogos se houver (para retomar execução)
        _local.dialog_answers = list(dialog_answers) if dialog_answers else []
        
        # Suprime avisos de dependência do requests (comum em addons antigos)
        warnings.filterwarnings("ignore", message=".*urllib3.*doesn't match a supported version.*")
        warnings.filterwarnings("ignore", category=SyntaxWarning)
        
        # Patch global no requests para evitar bloqueios (User-Agent)
        if 'requests' in sys.modules:
            import requests
            # Verifica se já foi patcheado para evitar duplicidade
            if not getattr(requests.Session, '_ua_patched', False):
                _orig_init = requests.Session.__init__
                def _new_init(self, *args, **kwargs):
                    _orig_init(self, *args, **kwargs)
                    # Define um User-Agent de navegador moderno
                    self.headers['User-Agent'] = MockXBMC.getUserAgent()
                
                requests.Session.__init__ = _new_init
                requests.Session._ua_patched = True
        
        # Limpa dados anteriores
        if hasattr(_local, 'data'):
            del _local.data
        # get_bridge_data() recriará o dicionário limpo automaticamente na próxima chamada
        
        # Simula os argumentos que o Kodi passa (URL, Handle, Params)
        # Separa a URL base dos parâmetros se necessário
        if '?' in param_string:
            base_url, query = param_string.split('?', 1)
            # Garante que a query string comece com ? para sys.argv[2]
            query_string = "?" + query if not query.startswith("?") else query
            sys.argv = [base_url, "1", query_string]
        else:
            # Se não tem ?, assume que é apenas a URL base ou apenas parâmetros antigos
            if param_string.startswith("plugin://"):
                sys.argv = [param_string, "1", ""]
            else:
                # Fallback para comportamento antigo (apenas params)
                sys.argv = ["plugin://bridge/", "1", param_string]
        
        # --- Configura sys.path para incluir bibliotecas do plugin ---
        plugin_dir = os.path.dirname(plugin_path)
        paths_to_add = [plugin_dir]
        
        # Tenta encontrar a raiz do addon (onde está o addon.xml)
        curr = plugin_dir
        addon_root = None
        while len(curr) > 3: # Evita loop infinito ou subir demais
            if os.path.exists(os.path.join(curr, 'addon.xml')):
                addon_root = curr
                break
            parent = os.path.dirname(curr)
            if parent == curr: break
            curr = parent
        
        if addon_root:
            # Adiciona resources/lib se existir (padrão Kodi)
            lib_path = os.path.join(addon_root, 'resources', 'lib')
            if os.path.exists(lib_path) and lib_path not in paths_to_add:
                paths_to_add.append(lib_path)
            
            # Adiciona outras pastas comuns de bibliotecas (lib, modules)
            for folder in ['lib', 'modules', 'include']:
                extra_lib = os.path.join(addon_root, folder)
                if os.path.exists(extra_lib) and extra_lib not in paths_to_add:
                    paths_to_add.append(extra_lib)
            
            # --- Resolve dependências (outros addons) ---
            # Tenta encontrar a pasta de addons pai para buscar dependências listadas no addon.xml
            addons_parent = os.path.dirname(addon_root)
            addon_xml_path = os.path.join(addon_root, 'addon.xml')
            
            if os.path.exists(addon_xml_path) and os.path.exists(addons_parent):
                try:
                    tree = ET.parse(addon_xml_path)
                    # Busca todas as tags <import addon="..."> dentro de <requires>
                    for import_tag in tree.iter('import'):
                        dep_id = import_tag.get('addon')
                        if dep_id and dep_id != 'xbmc.python':
                            dep_path = os.path.join(addons_parent, dep_id)
                            if os.path.exists(dep_path):
                                # Adiciona pastas de biblioteca do addon dependente (raiz, lib, modules)
                                for sub in ['', 'lib', 'modules', 'resources/lib']:
                                    dep_lib = os.path.join(dep_path, sub)
                                    if os.path.exists(dep_lib) and dep_lib not in paths_to_add:
                                        paths_to_add.append(dep_lib)
                except Exception as e:
                    print(f"Aviso: Erro ao carregar dependências de {addon_root}: {e}")

        for p in paths_to_add:
            if p not in sys.path:
                sys.path.insert(0, p)
        
        importlib.invalidate_caches()

        try:
            # Carrega o arquivo main.py do plugin dinamicamente
            # Usamos __main__ para garantir que blocos if __name__ == "__main__" rodem
            spec = importlib.util.spec_from_file_location("__main__", plugin_path)
            module = importlib.util.module_from_spec(spec)
            
            # Backup do __main__ real
            real_main = sys.modules.get("__main__")
            sys.modules["__main__"] = module
            
            try:
                # Executa o código do plugin
                spec.loader.exec_module(module)
            except SystemExit:
                pass
            finally:
                # Restaura __main__
                if real_main:
                    sys.modules["__main__"] = real_main
                else:
                    if "__main__" in sys.modules:
                        del sys.modules["__main__"]
            
            # Se o plugin tiver uma função router e não rodou pelo __main__ (ou se o __main__ não fez nada)
            # Verificamos se temos itens ou url resolvida. Se não, tentamos o router.
            data = get_bridge_data()
            if not data["items"] and not data["resolved_url"] and hasattr(module, 'router'):
                # Remove o '?' inicial para a função router, pois parse_qs não gosta dele
                # e a maioria dos plugins (como Erome) faz sys.argv[2][1:] no __main__
                arg = sys.argv[2]
                if arg.startswith('?'):
                    arg = arg[1:]
                module.router(arg)
                
        except DialogSelectError as e:
            print(f"[BRIDGE] Interrompido para seleção: {e.heading}")
            return {
                "items": [
                    {
                        "label": f"{item}",
                        "url": f"resume:select:{i}",
                        "isFolder": False,
                        "art": {"icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/Infobox_info_icon.svg/1024px-Infobox_info_icon.svg.png"}
                    }
                    for i, item in enumerate(e.options)
                ],
                "resolved_url": None,
                "media_info": {},
                "dialog_heading": e.heading
            }
        except DialogInputError as e:
            print(f"[BRIDGE] Interrompido para input: {e.heading}")
            return {
                "items": [],
                "resolved_url": None,
                "media_info": {},
                "dialog_input": {
                    "heading": e.heading,
                    "default": e.default
                }
            }
        except Exception as e:
            print(f"Erro no Plugin: {e}")
            import traceback
            traceback.print_exc()

        return get_bridge_data()
