# 📖 Guia do Usuário

Este player permite que você assista vídeos locais, do Google Drive ou de Plugins do Kodi.

## 🌐 Interface Web (Streamlit)

### Como Iniciar (Windows)
Para facilitar o uso, incluímos um arquivo `run.bat`.
1.  Dê um duplo clique em `run.bat` na pasta do projeto.
2.  Aguarde a instalação automática (na primeira vez).
3.  O navegador abrirá automaticamente com o player.

Ao acessar o endereço do player no navegador:

### Barra Lateral (Menu)
A barra lateral esquerda é o seu centro de controle.
1.  **Fonte de Mídia**: Escolha entre:
    *   **Plugins Kodi**: Lista os addons instalados no sistema.
    *   **Google Drive**: Conecta à sua conta do Google para listar vídeos.
    *   **Arquivos Locais**: Permite navegar pelas pastas do computador onde o player está rodando.
2.  **Seletor**: Dependendo da fonte, selecione o Plugin desejado ou clique em "Carregar Drive".
3.  **Botão Carregar**: Inicia a navegação na fonte escolhida.

### Configurando o Acesso ao Google Drive

Para que o player possa acessar seus vídeos e músicas no Google Drive, são necessários dois passos:

**1. Compartilhar sua pasta de mídias com o "bot" (Conta de Serviço):**

*   **Encontre o e-mail do bot:** No seu arquivo de credenciais (`.json` ou `secrets.toml`), localize o campo `client_email`. O valor será parecido com `nome-do-bot@seu-projeto.iam.gserviceaccount.com`.
*   **Compartilhe a pasta no Google Drive:**
    1.  Clique com o botão direito na sua pasta de mídias.
    2.  Vá em **Compartilhar** > **Compartilhar**.
    3.  Cole o `client_email` do bot no campo "Adicionar pessoas...".
    4.  Defina a permissão como **Leitor**.
    5.  Clique em **Enviar**.

**2. Informar ao player qual pasta acessar:**

*   **Encontre o ID da pasta:** Abra a pasta no navegador. A URL será `.../folders/ID_DA_PASTA`. Copie esse ID.
*   **Configure o `secrets.toml`:** Na raiz do projeto, crie ou edite o arquivo `.streamlit/secrets.toml` e adicione o ID:
    ```toml
    [media_player_drive]
    folder_id = "COLE_O_ID_DA_PASTA_AQUI"
    ```

Após esses passos, o botão "Testar Acesso ao Drive" na barra lateral deve confirmar a conexão.

### Deploy na Nuvem (Streamlit Cloud)

Quando o player está rodando na nuvem, o QR Code para acesso via celular precisa apontar para a URL pública do aplicativo (ex: `https://seu-app.streamlit.app`).

Para configurar isso, adicione a URL pública no seu arquivo `secrets.toml`:

```toml
[media_player_drive]
folder_id = "ID_DA_SUA_PASTA"
public_url = "https://seu-app.streamlit.app" # URL pública do seu app
```

Se a `public_url` não for definida, o sistema tentará detectar o IP local, o que é ideal para uso em uma rede Wi-Fi doméstica, mas não funcionará na nuvem.

### Navegação
*   **Pastas**: Clique nos botões da lista para entrar em pastas.
*   **Breadcrumbs**: No topo, você vê o caminho atual (ex: `Home > Filmes > Ação`). Use o botão **⬅️ Voltar** para subir um nível.

### Reprodução
Quando você seleciona um vídeo:
1.  Uma tela de **Pré-visualização** aparecerá com detalhes (Título, Artista, Ícone).
2.  Clique em **▶️ INICIAR REPRODUÇÃO**.
3.  O vídeo começará automaticamente.
4.  **QR Code**: Abra a seção "📱 Assistir no Celular" e escaneie o código para abrir o vídeo no seu smartphone.

---

## 🖥️ Interface Desktop (PyQt)

Uma janela de aplicativo tradicional para Windows/Linux/Mac.

### Controles Principais
*   **Abrir Vídeo**: Abre um arquivo local do seu computador.
*   **Carregar Plugin**: Abre uma lista para escolher um plugin instalado.
*   **Repositórios**: Permite baixar e instalar novos addons da internet ou de arquivos ZIP.

### Atalhos de Teclado
*   **Espaço**: Play / Pause.
*   **Seta Direita**: Avança 5 segundos.
*   **Seta Esquerda**: Volta 5 segundos.
*   **F** ou **Duplo Clique**: Tela Cheia.
*   **Esc**: Sai da Tela Cheia.

### Playlist
Ao passar o mouse no canto direito da tela, uma lista de reprodução aparecerá.
*   Se você abriu um arquivo local, ela mostrará todos os vídeos daquela pasta.
*   Se você está em um plugin, ela mostrará os próximos episódios ou vídeos da lista.

---

## ❓ Solução de Problemas

*   **"Pasta vazia ou erro ao carregar"**: Verifique se o plugin está funcionando ou se a internet está conectada. Alguns plugins antigos podem não ser compatíveis.
*   **Vídeo não toca (Tela preta)**: O vídeo pode ter proteção DRM (Widevine) ou usar um formato não suportado pelo navegador/player.