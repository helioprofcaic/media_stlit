import sys
import os
import importlib.util
import xml.etree.ElementTree as ET
import shutil
import json
import threading

# Armazenamento local para thread (suporte a multiusuário no Streamlit)
_local = threading.local()

# Lock global para garantir execução atômica de plugins (protege sys.argv e sys.modules)
_plugin_lock = threading.Lock()

def get_bridge_data():
    if not hasattr(_local, 'data'):
        _local.data = {
            "items": [],
            "resolved_url": None,
            "drm_info": None,
            "media_info": None
        }
    return _local.data

# Callback global para atualizações de metadados em tempo real
_metadata_callback = None

def register_metadata_callback(callback):
    global _metadata_callback
    _metadata_callback = callback

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
        return self.label

    def getPath(self):
        return self.path

    def setPath(self, path):
        self.path = path

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
        return '{"result": null}'

    @staticmethod
    def getSkinDir():
        return "skin.estuary"

    @staticmethod
    def getLanguage(format=0):
        return "English"

    @staticmethod
    def convertLanguage(language, format):
        return language

    @staticmethod
    def getSupportedMedia(mediaType):
        return ".mp4|.mkv|.avi|.mov|.wmv|.flv|.webm|.mp3|.wav|.m4v"

    @staticmethod
    def sleep(time):
        import time as t
        t.sleep(time / 1000.0)

    @staticmethod
    def getCondVisibility(condition):
        if 'inputstream.adaptive' in condition:
            return True
        return False

    @staticmethod
    def getInfoLabel(info):
        return ""

    @staticmethod
    def getUserAgent():
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    @staticmethod
    def getRegion(id):
        return "US"

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
            # Salva a URL para o VideoPlayer pegar via bridge_data
            data = get_bridge_data()
            data["resolved_url"] = item
            
            if listitem:
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
            pass
        def clear(self): pass
        def add(self, url, listitem=None, index=-1): pass
        def size(self): return 0
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
            return 0 if list else -1
            
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
        def __init__(self, windowId): pass
        def getProperty(self, key): return ""
        def setProperty(self, key, value): pass
        def clearProperty(self, key): pass
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
        if path.startswith("special://"):
            # Mapeia special://profile para ./kodi_profile
            path = path.replace("special://profile", "kodi_profile")
            path = path.replace("special://temp", "kodi_temp")
            path = path.replace("special://home", "kodi_home")
            # Remove o protocolo se sobrou algo desconhecido
            path = path.replace("special://", "")
            path = os.path.abspath(path)
        
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
            self.profile_path = os.path.join(os.getcwd(), "kodi_profile", "addon_data", self.id)
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
            if id == 'path': return os.path.join(os.getcwd(), "data", "addons", self.id)
            if id == 'version': return "1.0.0"
            if id == 'icon': 
                # Tenta encontrar o ícone na pasta de addons instalados
                icon_path = os.path.join(os.getcwd(), "data", "addons", self.id, "icon.png")
                if os.path.exists(icon_path): return icon_path
                
                # Tenta encontrar na pasta de plugins locais (Dev)
                icon_path = os.path.join(os.getcwd(), "plugin", self.id, "icon.png")
                if os.path.exists(icon_path): return icon_path
                
                return os.path.join(os.getcwd(), "data", "addons", self.id, "icon.png")
            return ''
        
        def getSetting(self, id):
            if id in self._settings:
                return str(self._settings[id])

            # Retorna valores padrão seguros para evitar erros de conversão (int/bool)
            if 'port' in id: return "8080"
            if 'whitelist' in id: return "false"
            if 'mpd' in id: return "false"
            return "" # Default genérico
            
        def setSetting(self, id, value):
            self._settings[id] = value
            self._save_settings()

        def getLocalizedString(self, id): return MockLocalizedString(str(id))

# --- Função Principal da Ponte ---

def setup_mocks():
    """Injeta os módulos falsos no sistema para o plugin importar."""
    if 'xbmc' not in sys.modules:
        sys.modules['xbmc'] = MockXBMC
        sys.modules['xbmcgui'] = MockXBMCGUI
        sys.modules['xbmcplugin'] = MockXBMCPlugin
        sys.modules['xbmcaddon'] = MockXBMCAddon
        sys.modules['xbmcvfs'] = MockXBMCVFS

    if 'kodi_six' not in sys.modules:
        kodi_six = type(sys)('kodi_six')
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

def run_plugin(plugin_path, param_string=""):
    """Executa o plugin e retorna os itens ou a URL resolvida."""
    with _plugin_lock:
        setup_mocks()
        
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
            spec = importlib.util.spec_from_file_location("plugin_main", plugin_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["plugin_main"] = module
            
            # Executa o código do plugin
            spec.loader.exec_module(module)
            
            # Se o plugin tiver uma função router e não rodou pelo __main__, chamamos manualmente
            if hasattr(module, 'router'):
                # Remove o '?' inicial para a função router, pois parse_qs não gosta dele
                # e a maioria dos plugins (como Erome) faz sys.argv[2][1:] no __main__
                arg = sys.argv[2]
                if arg.startswith('?'):
                    arg = arg[1:]
                module.router(arg)
                
        except Exception as e:
            print(f"Erro no Plugin: {e}")
            import traceback
            traceback.print_exc()

        return get_bridge_data()
