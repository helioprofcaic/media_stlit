# 📺 Media Player & Kodi Bridge

Um reprodutor de mídia híbrido que executa **Plugins do Kodi/XBMC** em um ambiente Python puro, apresentando tanto uma **Interface Web (Streamlit)** moderna quanto uma **Interface Desktop (PyQt6)** nativa.

Este projeto funciona como uma camada de compatibilidade, permitindo que você use seus addons favoritos do Kodi para streaming de conteúdo sem a necessidade de executar o aplicativo completo do Kodi. Ele foi projetado para ser flexível, seja para rodar em uma máquina local, em um servidor doméstico ou para fazer deploy na nuvem.

## ✨ Funcionalidades

*   **Kodi Bridge Core**: Um motor que simula a API do Kodi (`xbmc`, `xbmcgui`, `xbmcplugin`), permitindo executar addons de vídeo/áudio diretamente em Python puro.
*   **Interface Web (Streamlit)**:
    *   Navegação responsiva.
    *   Suporte a múltiplos usuários (sessões isoladas em threads).
    *   Geração de QR Code para assistir no celular.
    *   Integração com Google Drive e Explorador de Arquivos Locais.
*   **Gerenciamento de Plugins**:
    *   Navegador de repositórios para instalar novos addons.
    *   Instalação automática de dependências de plugins (ex: `requests`, `beautifulsoup4`) a partir do `addon.xml`.
*   **Interface Desktop (PyQt6)**:
    *   Player de vídeo nativo com suporte a aceleração de hardware.
    *   Gerenciador de janelas e atalhos de teclado.
*   **Suporte a DRM**: Identifica streams protegidos (Widevine).
*   **Instalação Automática**: Resolve dependências (`requests`, `beautifulsoup4`, etc.) listadas nos `addon.xml`.

## 🚀 Como Executar

### Pré-requisitos
*   Python 3.8+
*   Bibliotecas listadas em `requirements.txt` (se houver) ou instaladas via pip:
    ```bash
    pip install streamlit pyqt6 requests google-api-python-client google-auth-httplib2 google-auth-oauthlib
    ```

### 1. Versão Web (Streamlit)
Ideal para acesso remoto ou uso em navegador.

```bash
streamlit run streamlit_app.py
```

> **Nota:** Para usar o Google Drive, configure o `.streamlit/secrets.toml` com suas credenciais de Service Account.

#### 🪟 Windows (Facilitado)
Basta clicar duas vezes no arquivo `run.bat`. Ele irá:
1.  Criar o ambiente virtual automaticamente.
2.  Instalar as dependências.
3.  Iniciar o servidor Streamlit.

### 2. Versão Desktop
Ideal para performance máxima e uso local.

```bash
python video_player.py
```

## 📂 Estrutura do Projeto

*   `core/`: O coração do sistema (Kodi Bridge, Utils).
*   `plugin/`: Pasta para desenvolvimento de plugins locais.
*   `data/`: Armazena addons baixados, logs e configurações (ignorado pelo Git).
*   `docs/`: Documentação detalhada.

## 📄 Documentação
Veja a pasta `docs/` para manuais de usuário e detalhes técnicos.

---

#python #kodi #xbmc #media-player #streamlit #pyqt6 #kodi-plugins #google-drive #video-streaming #kodi-bridge