# 🛠️ Documentação Técnica

## Arquitetura do Sistema

O projeto utiliza uma arquitetura de **Mocking** (Simulação) para executar plugins escritos para o Kodi (XBMC) dentro de um ambiente Python padrão, desacoplando a lógica do plugin da interface gráfica.

### Componentes Principais

1.  **Kodi Bridge (`core/kodi_bridge.py`)**:
    *   Este é o núcleo do sistema. Ele intercepta as chamadas que os plugins fazem para `import xbmc`, `xbmcgui`, `xbmcplugin`.
    *   **Thread Safety**: Utiliza `threading.local()` para armazenar o estado da navegação (itens da lista, URL resolvida). Isso é crucial para o Streamlit, onde múltiplas sessões rodam simultaneamente em threads diferentes.
    *   **Dependency Injection**: Injeta módulos falsos (`MockXBMC`, `MockXBMCAddon`) no `sys.modules` antes de executar o plugin.

2.  **Streamlit App (`streamlit_app.py`)**:
    *   Frontend Web.
    *   Gerencia o estado da sessão (`st.session_state`) para histórico de navegação e itens atuais.
    *   Usa `subprocess` para instalar dependências (`pip`) listadas no `addon.xml` em tempo de execução.

3.  **Desktop Player (`video_player.py`)**:
    *   Frontend Desktop usando PyQt6.
    *   Possui um `StreamBuffer` personalizado para lidar com streaming HTTP que exige headers específicos (User-Agent, Referer), algo que o `QMediaPlayer` padrão não faz nativamente.

4.  **Google Storage (`google_storage.py`)**:
    *   Gerencia a conexão com a API do Google Drive.
    *   Usa `st.secrets` para autenticação segura via Service Account.

## Estrutura de Pastas

```text
root/
├── core/               # Lógica do sistema
│   ├── kodi_bridge.py  # Simulação da API Kodi
│   ├── repository.py   # Gerenciador de downloads de addons
│   └── utils.py        # Funções auxiliares e paths
├── data/               # (Ignorado pelo Git)
│   ├── addons/         # Onde os plugins são instalados
│   └── player.log      # Logs de execução
├── docs/               # Documentação
├── plugin/             # Pasta para desenvolvimento local de plugins
├── streamlit_app.py    # Entry point Web
└── video_player.py     # Entry point Desktop
```

## Fluxo de Execução de um Plugin

1.  O usuário seleciona um plugin na interface.
2.  O sistema localiza o `main.py` ou `default.py` do plugin.
3.  A função `run_plugin(path, params)` é chamada.
4.  O **Bridge**:
    *   Bloqueia a thread (`_plugin_lock`) para evitar conflito de `sys.argv`.
    *   Limpa o `sys.modules` de execuções anteriores.
    *   Configura os Mocks.
    *   Executa o arquivo Python do plugin.
5.  O Plugin chama `xbmcplugin.addDirectoryItem`.
6.  O **MockXBMCPlugin** captura esses itens e os salva na memória local da thread.
7.  O Bridge retorna a lista de itens para a interface (Streamlit ou PyQt) renderizar.

## Dependências e Addons

O sistema possui um resolvedor de dependências simples em `streamlit_app.py` -> `install_dependencies`.
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

[drive]
folder_id = "ID_DA_PASTA_RAIZ"
```
**Nota:** Vídeos no Drive devem ter permissão de leitura para o e-mail da Service Account ou estarem públicos (link compartilhável) para o streaming funcionar via URL direta.