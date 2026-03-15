try:
    import requests
except ImportError:
    requests = None
import zipfile
import io
import xml.etree.ElementTree as ET
import os
import shutil
from core.utils import log_to_file, ADDONS_DIR, PLUGINS_REPO_DIR

# Tenta importar PyQt6 apenas se necessário, para permitir uso em ambientes sem GUI (Streamlit)
try:
    from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                                 QPushButton, QListWidget, QListWidgetItem, QMessageBox, QInputDialog, QApplication)
    from PyQt6.QtCore import Qt
    HAS_QT = True
    from core.update_addons_xml import fetch_and_update_addons_xml
except ImportError:
    HAS_QT = False
    QDialog = object # Mock para herança não falhar

def parse_addons_xml(xml_content, base_url):
    """Função auxiliar pura para processar XML de addons e retornar lista de dicionários."""
    addons_data = []
    try:
        root = ET.fromstring(xml_content)
        # Lógica de redirecionamento de repositório poderia vir aqui, 
        # mas simplificaremos para retornar os addons diretos
        for addon in root.findall('addon'):
            addon_id = addon.get('id')
            name = addon.get('name')
            version = addon.get('version')
            zip_url = f"{base_url}{addon_id}/{addon_id}-{version}.zip"
            addons_data.append({
                'name': name,
                'version': version,
                'id': addon_id,
                'url': zip_url
            })
    except Exception as e:
        log_to_file(f"XML Parse Error: {e}")
    return addons_data

class RepositoryBrowser(QDialog):
    """Janela para navegar e instalar addons de repositórios."""
    def __init__(self, parent=None):
        if not HAS_QT:
            return
        super().__init__(parent)
        self.setWindowTitle("Gerenciador de Repositórios")
        self.resize(700, 500)
        self.parent_player = parent
        
        # Lista de Repositórios (StreamedEZ adicionado por padrão)
        self.repos = [
            {"name": "Local Plugins (media_stlit/plugin)", "url": PLUGINS_REPO_DIR},
            {"name": "StreamedEZ Repo", "url": "https://blazeymcblaze.github.io/streamedez/"}
        ]
        
        self.scan_installed_repos()
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Seletor de Repo
        repo_layout = QHBoxLayout()
        repo_layout.addWidget(QLabel("Repositório:"))
        self.repo_combo = QComboBox()
        for repo in self.repos:
            self.repo_combo.addItem(repo["name"], repo["url"])
        repo_layout.addWidget(self.repo_combo)
        
        self.add_repo_btn = QPushButton("+")
        self.add_repo_btn.setToolTip("Adicionar URL de Repositório")
        self.add_repo_btn.clicked.connect(self.add_custom_repo)
        repo_layout.addWidget(self.add_repo_btn)

        self.load_btn = QPushButton("Carregar Addons")
        self.load_btn.clicked.connect(self.load_addons)
        repo_layout.addWidget(self.load_btn)
        layout.addLayout(repo_layout)

        self.update_btn = QPushButton("Atualizar Addons.xml")
        self.update_btn.clicked.connect(self.update_addons_xml)
        layout.addWidget(self.update_btn)
        
        # Lista de Addons
        self.addons_list = QListWidget()
        layout.addWidget(self.addons_list)
        
        # Botão Instalar
        self.install_btn = QPushButton("Instalar Addon Selecionado")
        self.install_btn.clicked.connect(self.install_addon)
        self.install_btn.setEnabled(False)
        layout.addWidget(self.install_btn)
        
        self.status_label = QLabel("Selecione um repositório e clique em Carregar.")
        layout.addWidget(self.status_label)

    def scan_installed_repos(self):
        """Escaneia addons instalados para encontrar repositórios e adicioná-los à lista."""
        dirs_to_scan = []
        if os.path.exists(ADDONS_DIR):
            dirs_to_scan.append(ADDONS_DIR)
        if os.path.exists(PLUGINS_REPO_DIR):
            dirs_to_scan.append(PLUGINS_REPO_DIR)

        for base_dir in dirs_to_scan:
            for item_name in os.listdir(base_dir):
                addon_path = os.path.join(base_dir, item_name)
                addon_xml = os.path.join(addon_path, 'addon.xml')
                
                if os.path.isdir(addon_path) and os.path.exists(addon_xml):
                    try:
                        with open(addon_xml, 'r', encoding='utf-8', errors='ignore') as f:
                            xml_content = f.read()
                        root = ET.fromstring(xml_content)
                        
                        # Verifica se é um repositório
                        repo_ext = None
                        for ext in root.findall('extension'):
                            if ext.get('point') == 'xbmc.addon.repository':
                                repo_ext = ext
                                break
                        
                        if repo_ext:
                            repo_name = root.get('name', item_name)
                            # Pega a última definição de diretório (geralmente a versão mais nova)
                            dirs = repo_ext.findall('dir')
                            if dirs:
                                target_dir = dirs[-1]
                                info = target_dir.find('info')
                                if info is not None and info.text:
                                    self.repos.append({"name": f"{repo_name} [Instalado]", "url": info.text})
                    except Exception as e:
                        log_to_file(f"Erro ao escanear repo {item_name}: {e}")

    def add_custom_repo(self):
        url, ok = QInputDialog.getText(self, "Adicionar Repositório", "URL do Repositório (onde está o addons.xml):")
        if ok and url:
            if not url.endswith('/'):
                url += '/'
            self.repo_combo.addItem(f"Custom: {url}", url)
            self.repo_combo.setCurrentIndex(self.repo_combo.count() - 1)

    def update_addons_xml(self):
        """Chama o script para atualizar os addons.xml locais a partir do repositório remoto."""
        repo_url = self.repo_combo.currentData()
        
        # A função de atualização espera uma URL, não um caminho local
        if not repo_url or os.path.isdir(repo_url):
            QMessageBox.warning(self, "Ação Inválida", "Selecione um repositório remoto para poder usar esta função.")
            return

        self.status_label.setText(f"Atualizando addons a partir de {repo_url}...")
        QApplication.processEvents()
        fetch_and_update_addons_xml(repo_url, ADDONS_DIR)
        self.status_label.setText("Processo de atualização concluído. Verifique o log.")
        QMessageBox.information(self, "Concluído", "O script de atualização foi executado. Verifique o arquivo 'player.log' para detalhes.")

    def get_addons_list(self, repo_url):
        """Método desacoplado da UI para obter addons de uma URL."""
        if not requests: return []
        
        candidates = []
        if repo_url.endswith('.xml'):
            candidates.append(repo_url)
        else:
            base = repo_url if repo_url.endswith('/') else f"{repo_url}/"
            candidates.append(base + "addons.xml")
            candidates.append(base + "zips/addons.xml")
            candidates.append(base + "addon.xml")
        
        response = None
        xml_url = None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        for url in candidates:
            try:
                r = requests.get(url, timeout=15, headers=headers)
                if r.status_code == 200:
                    response = r
                    xml_url = url
                    break
            except:
                pass
        
        if response and xml_url:
            base_url = xml_url.rsplit('/', 1)[0] + '/'
            content = response.content.decode('utf-8', errors='ignore')
            return parse_addons_xml(content, base_url)
        return []

    def load_addons(self):
        repo_url = self.repo_combo.currentData()
        
        # Verifica se é repositório local
        if os.path.isdir(repo_url):
            self.load_local_addons(repo_url)
            return

        if not requests:
            QMessageBox.critical(self, "Erro", "Biblioteca 'requests' não encontrada.")
            return
        
        self.status_label.setText("Baixando lista de addons...")
        self.addons_list.clear()
        QApplication.processEvents()
        
        # Define candidatos para a URL do XML
        candidates = []
        if repo_url.endswith('.xml'):
            candidates.append(repo_url)
        else:
            base = repo_url if repo_url.endswith('/') else f"{repo_url}/"
            candidates.append(base + "addons.xml")
            candidates.append(base + "addon.xml")
            candidates.append(base + "zips/addons.xml") # Estrutura comum em alguns repos
            
            # Suporte inteligente para GitHub (converte URL de visualização para Raw)
            if "github.com" in repo_url and "raw.githubusercontent.com" not in repo_url:
                try:
                    # Remove .git e barras finais
                    clean_url = repo_url.replace(".git", "").rstrip('/')
                    parts = clean_url.split('/')
                    # Espera formato https://github.com/usuario/repo
                    if len(parts) >= 5:
                        user = parts[3]
                        repo = parts[4]
                        # Tenta branches comuns
                        for branch in ['master', 'main']:
                            raw_base = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/"
                            candidates.append(raw_base + "addons.xml")
                            candidates.append(raw_base + "zips/addons.xml")
                            candidates.append(raw_base + "addon.xml")
                except Exception as e:
                    print(f"Erro ao processar URL do GitHub: {e}")
        
        response = None
        xml_url = None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        for url in candidates:
            try:
                r = requests.get(url, timeout=15, headers=headers)
                if r.status_code == 200:
                    response = r
                    xml_url = url
                    break
            except:
                pass
        
        if not response:
            self.status_label.setText("Erro ao carregar lista.")
            QMessageBox.critical(self, "Erro", f"Falha ao encontrar arquivo de addons (404) em:\n{repo_url}\n\nVerifique a URL.")
            return

        # Base URL inicial é o diretório do XML encontrado
        base_url = xml_url.rsplit('/', 1)[0] + '/'
        
        try:
            # Decodificação robusta para evitar erros de caracteres estranhos
            content = response.content.decode('utf-8', errors='ignore')
            root = ET.fromstring(content)
            
            # Handle Repository Addon Definition (redirect)
            if root.tag == 'addon':
                repo_ext = None
                for ext in root.findall('extension'):
                    if ext.get('point') == 'xbmc.addon.repository':
                        repo_ext = ext
                        break
                
                if repo_ext:
                    # Find valid dir with info and datadir
                    target_dir = None
                    for d in repo_ext.findall('dir'):
                        if d.find('info') is not None and d.find('datadir') is not None:
                            # Continua o loop para que a última definição (geralmente a mais recente) seja usada.
                            target_dir = d
                    
                    if target_dir:
                        info_url = target_dir.find('info').text
                        datadir_url = target_dir.find('datadir').text
                        
                        self.status_label.setText(f"Redirecionando para {info_url}...")
                        QApplication.processEvents()
                        
                        response = requests.get(info_url, timeout=15, headers=headers)
                        response.raise_for_status()
                        
                        content = response.content.decode('utf-8', errors='ignore')
                        root = ET.fromstring(content)
                        
                        base_url = datadir_url if datadir_url.endswith('/') else f"{datadir_url}/"

            for addon in root.findall('addon'):
                addon_id = addon.get('id')
                name = addon.get('name')
                version = addon.get('version')
                
                item_text = f"{name} ({version}) - {addon_id}"
                item = QListWidgetItem(item_text)
                # Salva dados para instalação: URL do zip padrão do Kodi
                # Formato: repo/id/id-version.zip
                zip_url = f"{base_url}{addon_id}/{addon_id}-{version}.zip"
                item.setData(Qt.ItemDataRole.UserRole, {'id': addon_id, 'url': zip_url, 'name': name})
                self.addons_list.addItem(item)
            
            count = self.addons_list.count()
            self.status_label.setText(f"{count} addons encontrados.")
            self.install_btn.setEnabled(count > 0)
            
            if count == 0:
                QMessageBox.warning(self, "Aviso", "Nenhum addon encontrado neste repositório.\nVerifique se a URL está correta.")
            
        except Exception as e:
            self.status_label.setText(f"Erro ao carregar lista.")
            QMessageBox.critical(self, "Erro", f"Falha ao ler addons.xml:\n{e}")
            log_to_file(f"Repo Error: {e}")

    def load_local_addons(self, path):
        self.status_label.setText("Escaneando plugins locais...")
        self.addons_list.clear()
        QApplication.processEvents()
        
        count = 0
        try:
            for item_name in os.listdir(path):
                item_path = os.path.join(path, item_name)
                if os.path.isdir(item_path):
                    addon_xml = os.path.join(item_path, 'addon.xml')
                    if os.path.exists(addon_xml):
                        try:
                            with open(addon_xml, 'r', encoding='utf-8', errors='ignore') as f:
                                xml_content = f.read()
                            root = ET.fromstring(xml_content)
                            addon_id = root.get('id')
                            name = root.get('name')
                            version = root.get('version')
                            
                            item_text = f"{name} ({version}) - {addon_id} [LOCAL]"
                            item = QListWidgetItem(item_text)
                            item.setData(Qt.ItemDataRole.UserRole, {'id': addon_id, 'url': item_path, 'name': name, 'is_local': True})
                            self.addons_list.addItem(item)
                            count += 1
                        except Exception as e:
                            log_to_file(f"Erro ao ler addon.xml local {item_name}: {e}")
            
            self.status_label.setText(f"{count} addons locais encontrados.")
            self.install_btn.setEnabled(count > 0)
        except Exception as e:
            self.status_label.setText(f"Erro ao ler pasta local.")
            log_to_file(f"Local Repo Error: {e}")

    def install_addon(self):
        item = self.addons_list.currentItem()
        if not item:
            return
            
        data = item.data(Qt.ItemDataRole.UserRole)
        
        if data.get('is_local'):
            self.install_local_addon(data)
            return

        self.status_label.setText(f"Baixando {data['name']}...")
        QApplication.processEvents()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            response = requests.get(data['url'], stream=True, timeout=30, headers=headers)
            response.raise_for_status()
            
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                z.extractall(ADDONS_DIR)
                
            self.status_label.setText(f"Sucesso! {data['name']} instalado em 'data/addons'.")
            QMessageBox.information(self, "Instalação", f"O addon '{data['name']}' foi instalado com sucesso!\n\nVocê pode carregá-lo agora pelo menu 'Carregar Plugin'.")
            
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg:
                error_msg = "Arquivo não encontrado no servidor (Erro 404).\nA URL do repositório pode estar desatualizada."
            self.status_label.setText("Falha na instalação.")
            QMessageBox.critical(self, "Erro de Instalação", error_msg)
            log_to_file(f"Install Error: {e}")

    def install_local_addon(self, data):
        src_path = data['url']
        addon_id = data['id']
        dest_path = os.path.join(ADDONS_DIR, addon_id)
        
        self.status_label.setText(f"Copiando {data['name']}...")
        QApplication.processEvents()
        
        try:
            if os.path.exists(dest_path):
                shutil.rmtree(dest_path)
            
            shutil.copytree(src_path, dest_path)
            
            self.status_label.setText(f"Sucesso! {data['name']} instalado.")
            QMessageBox.information(self, "Instalação", f"O addon '{data['name']}' foi copiado para a pasta de addons.")
        except Exception as e:
            self.status_label.setText("Falha na cópia local.")
            QMessageBox.critical(self, "Erro", f"Falha ao copiar arquivos:\n{e}")
            log_to_file(f"Local Install Error: {e}")
