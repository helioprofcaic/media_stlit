# 📖 Guia do Usuário

Este player permite que você assista vídeos locais, do Google Drive ou de Plugins do Kodi.

## 🌐 Interface Web (Streamlit)

Ao acessar o endereço do player no navegador:

### Barra Lateral (Menu)
A barra lateral esquerda é o seu centro de controle.
1.  **Fonte de Mídia**: Escolha entre:
    *   **Plugins Kodi**: Lista os addons instalados no sistema.
    *   **Google Drive**: Conecta à sua conta do Google para listar vídeos.
    *   **Arquivos Locais**: Permite navegar pelas pastas do computador onde o player está rodando.
2.  **Seletor**: Dependendo da fonte, selecione o Plugin desejado ou clique em "Carregar Drive".
3.  **Botão Carregar**: Inicia a navegação na fonte escolhida.

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