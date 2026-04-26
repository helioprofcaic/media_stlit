import streamlit as st
import requests
import base64
import json
import urllib.parse

# Usa uma sessão global para manter cookies e configurações de retry
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})

def rewrite_manifest(content, base_url, proxy_self_url, headers_b64):
    """Reescreve as URLs dentro de um manifesto HLS para apontar para o proxy web."""
    lines = content.splitlines()
    new_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('#'):
            if 'URI="' in line:
                try:
                    pre_uri, post_uri = line.split('URI="', 1)
                    uri, rest = post_uri.split('"', 1)
                    abs_url = urllib.parse.urljoin(base_url, uri)
                    url_b64 = base64.urlsafe_b64encode(abs_url.encode()).decode()
                    proxy_url = f"{proxy_self_url}?proxy_url={url_b64}&proxy_headers={headers_b64}"
                    line = f'{pre_uri}URI="{proxy_url}"{rest}'
                except Exception as e:
                    print(f"Error rewriting URI in tag: {e}")
            new_lines.append(line)
        else:
            abs_url = urllib.parse.urljoin(base_url, line)
            url_b64 = base64.urlsafe_b64encode(abs_url.encode()).decode()
            proxy_url = f"{proxy_self_url}?proxy_url={url_b64}&proxy_headers={headers_b64}"
            new_lines.append(proxy_url)
            
    return "\n".join(new_lines)

def handle_proxy_request():
    """
    Função principal que atua como um proxy.
    Busca o conteúdo da URL real com os headers e o serve para o cliente.
    """
    query_params = st.query_params
    target_url_b64 = query_params.get("proxy_url")
    headers_b64 = query_params.get("proxy_headers")

    if not target_url_b64 or not headers_b64:
        st.error("Proxy Error: Missing URL or Headers.")
        return

    try:
        target_url = base64.urlsafe_b64decode(target_url_b64).decode('utf-8')
        headers = json.loads(base64.urlsafe_b64decode(headers_b64).decode('utf-8'))
    except Exception as e:
        st.error(f"Proxy Error: Invalid encoding. {e}")
        return

    try:
        resp = session.get(target_url, headers=headers, stream=True, timeout=20)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '')
        is_manifest = 'mpegurl' in content_type.lower() or target_url.endswith('.m3u8')

        if is_manifest:
            manifest_content = resp.text
            proxy_self_url = st.secrets.get("media_player_drive", {}).get("public_url", "").strip("/")
            if not proxy_self_url:
                 st.error("Proxy Error: `public_url` não configurado nos secrets.toml.")
                 return

            rewritten_manifest = rewrite_manifest(manifest_content, target_url, proxy_self_url, headers_b64)
            st.code(rewritten_manifest, language='text', line_numbers=False)
        else:
            # Para segmentos de vídeo, st.write(bytes) serve o conteúdo bruto.
            st.write(resp.content)

    except requests.exceptions.RequestException as e:
        st.error(f"Proxy Network Error for {target_url}: {e}")
    except Exception as e:
        st.error(f"Proxy General Error: {e}")