# 🛠️ Documentação Técnica

## Arquitetura do Sistema

O projeto utiliza uma arquitetura de **Mocking** (Simulação) para executar plugins escritos para o Kodi (XBMC) dentro de um ambiente Python padrão, desacoplando a lógica do plugin da interface gráfica.

### Componentes Principais

1.  **Kodi Bridge (`core/kodi_bridge.py`)**:
    *   Este é o núcleo do sistema. Ele intercepta as chamadas que os plugins fazem para `import xbmc`, `xbmcgui`, `xbmcplugin`.
    *   **Thread Safety**: Utiliza `threading.local()` para armazenar o estado da navegação (itens da lista, URL resolvida). Isso é crucial para o Streamlit, onde múltiplas sessões rodam simultaneamente em threads diferentes.
    *   **Dependency Injection**: Injeta módulos falsos (`MockXBMC`, `MockXBMCAddon`) no `sys.modules` antes de executar o plugin.
    *   **Detecção de Plataforma**: Identifica automaticamente o sistema operacional (Windows/Linux) e a arquitetura (x64, arm, etc.) para retornar os binários corretos em plugins que dependem de código nativo (ex: Elementum), simulando a configuração `binary_platform`.

2.  **Streamlit App (`streamlit_app.py`)**:
    *   Frontend Web.
    *   Gerencia o estado da sessão (`st.session_state`) para histórico de navegação e itens atuais.
    *   **Modularização**: A lógica foi dividida em módulos (`modules/`) para melhor organização:
        *   `modules/navigation.py`: Gerencia navegação, execução de plugins e histórico.
        *   `modules/drive_sync.py`: Sincronização com Google Drive e plugins locais.
        *   `modules/utils.py`: Utilitários gerais e instalação de dependências.

3.  **Desktop Player (`video_player.py`)**:
    *   Frontend Desktop usando PyQt6.
    *   Possui um `StreamBuffer` personalizado para lidar com streaming HTTP que exige headers específicos (User-Agent, Referer), algo que o `QMediaPlayer` padrão não faz nativamente.

4.  **Google Storage (`google_storage.py`)**:
    *   Gerencia a conexão com a API do Google Drive.
    *   Usa `st.secrets` para autenticação segura via Service Account.

5.  **Serviços em Background (`core/services.py`)**:
    *   Detecta e executa scripts de serviço (`service.py`) definidos nos `addon.xml`.
    *   Essencial para addons como **Elementum** que iniciam servidores locais (daemon) para processar torrents antes do streaming.
    *   Roda em threads separadas para não bloquear a interface principal.

## Estrutura de Pastas

```text
root/
├── core/               # Lógica do sistema
│   ├── kodi_bridge.py  # Simulação da API Kodi
│   ├── services.py     # Gerenciador de serviços (daemons)
│   ├── repository.py   # Gerenciador de downloads de addons
│   └── utils.py        # Funções auxiliares e paths
├── data/               # (Ignorado pelo Git)
│   ├── addons/         # Onde os plugins são instalados
│   └── player.log      # Logs de execução
├── docs/               # Documentação
├── modules/            # Módulos do Streamlit App
│   ├── drive_sync.py   # Sincronização
│   ├── navigation.py   # Navegação e execução
│   └── utils.py        # Utilitários
├── playlists/          # Arquivos .strm para acesso rápido local
├── plugin/             # Pasta para desenvolvimento local de plugins
├── streamlit_app.py    # Entry point Web
└── video_player.py     # Entry point Desktop
```

## Fluxo de Execução de um Plugin

1.  O usuário seleciona um plugin na interface.
2.  O sistema localiza o `main.py` ou `default.py` do plugin.
3.  A função `run_plugin(path, params)` é chamada (agora via `modules.navigation`).
4.  O **Bridge**:
    *   Bloqueia a thread (`_plugin_lock`) para evitar conflito de `sys.argv`.
    *   Limpa o `sys.modules` de execuções anteriores.
    *   Configura os Mocks.
    *   Executa o arquivo Python do plugin.
5.  O Plugin chama `xbmcplugin.addDirectoryItem`.
6.  O **MockXBMCPlugin** captura esses itens e os salva na memória local da thread.
7.  O Bridge retorna a lista de itens para a interface (Streamlit ou PyQt) renderizar.

## Reprodução de Streams e HLS

O player implementa uma lógica robusta para lidar com streams complexos, especialmente IPTV e HLS (`.m3u8`):

1.  **Resolução de Redirecionamentos (302 Found)**:
    *   Muitos serviços de IPTV usam URLs temporárias ou tokens que expiram.
    *   O `streamlit_app.py` intercepta URLs `.m3u8`, faz requisições `HEAD` sucessivas para seguir redirecionamentos e entrega a URL final e estável para o player HTML5.
    *   Isso previne travamentos onde o player tentaria re-autenticar a cada segmento do vídeo.

2.  **Arquivos .strm**:
    *   Suporte nativo a arquivos de texto contendo URLs diretas (YouTube, M3U8, etc).

## Dependências e Addons

O sistema possui um resolvedor de dependências simples em `modules/utils.py` -> `install_dependencies`.
Ele lê o arquivo `addon.xml`, mapeia nomes de pacotes do Kodi (ex: `script.module.requests`) para pacotes PyPI (`requests`) e os instala automaticamente.

## Google Drive Integration

Para funcionar, o arquivo `.streamlit/secrets.toml` deve estar configurado:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key = "..."
client_email = "..."
...

[media_player_drive]
folder_id = "ID_DA_PASTA_RAIZ"
```
**Nota:** Vídeos no Drive devem ter permissão de leitura para o e-mail da Service Account ou estarem públicos (link compartilhável) para o streaming funcionar via URL direta.