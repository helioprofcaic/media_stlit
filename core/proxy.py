import http.server
import socketserver
import threading
import requests
import urllib.parse
import base64
import re
import socket
import json

# Sessão global para manter cookies (importante para passar por ad-gates)
session = requests.Session()

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Logs básicos para o console
        print(f"Proxy: {args[0]}")

    def do_GET(self):
        # Nova estrutura de URL: /proxy/[B64_URL]/playlist.m3u8 ou segment.ts?headers=[B64_HEADERS]
        path = self.path
        
        try:
            # Extrai o base64 da URL codificada no caminho
            # Padrão: /proxy/(BASE64)/(EXT)
            match = re.search(r'/proxy/([^/]+)/', path)
            if not match:
                # Tenta formato antigo por compatibilidade se houver ?url=
                query = urllib.parse.urlparse(path).query
                params = urllib.parse.parse_qs(query)
                url_b64 = params.get('url', [None])[0]
            else:
                url_b64 = match.group(1)
            
            if not url_b64:
                self.send_error(400, "Missing encoded URL")
                return

            # Decodifica a URL alvo
            target_url = base64.urlsafe_b64decode(url_b64).decode('utf-8')
            
            # Extrai os headers da query string (sempre no final)
            query = urllib.parse.urlparse(path).query
            params = urllib.parse.parse_qs(query)
            headers_b64 = params.get('headers', [None])[0]
            headers = {}
            if headers_b64:
                headers_b64 = headers_b64.replace(' ', '+')
                headers = json.loads(base64.urlsafe_b64decode(headers_b64).decode('utf-8'))
                
        except Exception as e:
            print(f"Proxy Decoding Error: {e} | Path: {path}")
            self.send_error(400, "Invalid encoding")
            return

        try:
            # Faz a requisição usando a sessão global
            resp = session.get(target_url, headers=headers, stream=True, timeout=15)
            
            if resp.status_code >= 400:
                print(f"Proxy Error {resp.status_code} for target: {target_url}")
                try:
                    text_preview = resp.text[:200]
                    print(f"Response text preview: {text_preview}")
                except: pass

            self.send_response(resp.status_code)
            
            content_type = resp.headers.get('Content-Type', '')
            is_manifest = 'mpegurl' in content_type.lower() or 'text/plain' in content_type.lower() or \
                          '.m3u8' in target_url or '.txt' in target_url or \
                          '/playlist.m3u8' in path
            
            # Repassa headers ignorando os de controle (menos Content-Length para segmentos)
            for k, v in resp.headers.items():
                if k.lower() not in ['content-encoding', 'transfer-encoding', 'connection', 'content-type']:
                     if k.lower() == 'content-length' and is_manifest:
                         continue
                     self.send_header(k, v)
            
            if is_manifest:
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                content = resp.text
                new_content = self.rewrite_manifest(content, target_url, headers)
                encoded_content = new_content.encode('utf-8')
                self.send_header('Content-Length', str(len(encoded_content)))
                self.end_headers()
                self.wfile.write(encoded_content)
            else:
                self.send_header('Content-Type', content_type)
                self.end_headers()
                for chunk in resp.iter_content(chunk_size=128*1024):
                    if chunk:
                        self.wfile.write(chunk)
                        
        except Exception as e:
            print(f"Proxy Fetch Error: {e}")
            try:
                self.send_error(500, str(e))
            except:
                pass

    def rewrite_manifest(self, content, base_url, headers):
        lines = content.splitlines()
        new_lines = []
        
        headers_b64 = base64.urlsafe_b64encode(json.dumps(headers).encode()).decode()
        host = self.headers.get('Host')
        proxy_root = f"http://{host}/proxy"

        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('#'):
                # Verifica se há URI="..." dentro da tag (ex: #EXT-X-KEY, #EXT-X-MAP)
                if 'URI="' in line:
                    try:
                        pre_uri, post_uri = line.split('URI="', 1)
                        uri, rest = post_uri.split('"', 1)
                        
                        abs_url = urllib.parse.urljoin(base_url, uri)
                        is_sub_manifest = '.m3u8' in abs_url or '.txt' in abs_url
                        ext_falsa = "playlist.m3u8" if is_sub_manifest else "segment.ts"
                        url_b64 = base64.urlsafe_b64encode(abs_url.encode()).decode()
                        proxy_url = f"{proxy_root}/{url_b64}/{ext_falsa}?headers={headers_b64}"
                        
                        line = f'{pre_uri}URI="{proxy_url}"{rest}'
                    except Exception as e:
                        print(f"Error rewriting URI in tag: {e}")
                new_lines.append(line)
            else:
                # URL de segmento ou de outro manifest
                abs_url = urllib.parse.urljoin(base_url, line)
                
                # Identifica se é outro manifesto
                is_sub_manifest = '.m3u8' in abs_url or '.txt' in abs_url
                ext_falsa = "playlist.m3u8" if is_sub_manifest else "segment.ts"
                
                url_b64 = base64.urlsafe_b64encode(abs_url.encode()).decode()
                # URL formatada como caminho: /proxy/[B64_URL]/[EXT]?headers=[B64_HEADERS]
                proxy_url = f"{proxy_root}/{url_b64}/{ext_falsa}?headers={headers_b64}"
                new_lines.append(proxy_url)
                
        return "\n".join(new_lines)

class ProxyServer:
    def __init__(self):
        self.port = self.find_free_port()
        self.server = None
        self.thread = None

    def find_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def start(self):
        handler = ProxyHandler
        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"Proxy Local rodando em: http://127.0.0.1:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def get_proxy_url(self, target_url, headers):
        url_b64 = base64.urlsafe_b64encode(target_url.encode()).decode()
        headers_b64 = base64.urlsafe_b64encode(json.dumps(headers).encode()).decode()
        # Formato de caminho para evitar que o player se perca
        return f"http://127.0.0.1:{self.port}/proxy/{url_b64}/playlist.m3u8?headers={headers_b64}"