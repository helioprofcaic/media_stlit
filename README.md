# 📺 Media Player & Kodi Bridge

Um reprodutor de mídia híbrido capaz de rodar **Plugins do Kodi** e acessar o **Google Drive**, com duas interfaces distintas: uma versão Desktop (PyQt6) e uma versão Web (Streamlit).

## ✨ Funcionalidades

*   **Kodi Bridge Core**: Um motor que simula a API do Kodi (`xbmc`, `xbmcgui`, `xbmcplugin`), permitindo executar addons de vídeo/áudio diretamente em Python puro.
*   **Interface Web (Streamlit)**:
    *   Navegação responsiva.
    *   Suporte a múltiplos usuários (sessões isoladas).
    *   Geração de QR Code para assistir no celular.
    *   Integração com Google Drive e Explorador de Arquivos Locais.
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