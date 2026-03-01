import requests
import json
import os
import sys

# Define caminhos
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCES_DIR = os.path.join(PLUGIN_DIR, 'resources')

if not os.path.exists(RESOURCES_DIR):
    os.makedirs(RESOURCES_DIR)

COUNTRIES_FILE = os.path.join(RESOURCES_DIR, 'countries.json')
TAGS_FILE = os.path.join(RESOURCES_DIR, 'tags.json')

BASE_API = "https://de1.api.radio-browser.info"

def update_data():
    print(f"Salvando em: {RESOURCES_DIR}")
    
    # 1. Países
    print("Baixando lista de países...")
    try:
        r = requests.get(f"{BASE_API}/json/countries", timeout=30)
        r.raise_for_status()
        with open(COUNTRIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(r.json(), f, ensure_ascii=False)
        print("✅ Países salvos com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao baixar países: {e}")

    # 2. Tags
    print("Baixando lista de tags...")
    try:
        r = requests.get(f"{BASE_API}/json/tags", timeout=30)
        r.raise_for_status()
        with open(TAGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(r.json(), f, ensure_ascii=False)
        print("✅ Tags salvas com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao baixar tags: {e}")

if __name__ == "__main__":
    update_data()