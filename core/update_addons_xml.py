import os
import xml.etree.ElementTree as ET
import requests
from core.utils import log_to_file

def fetch_and_update_addons_xml(repo_url, addons_dir):
    """
    Fetches the addons.xml file from a repository URL, parses it,
    and updates the local addon.xml files with the information.
    
    Args:
        repo_url (str): The URL of the repository.
        addons_dir (str): The directory where addons are installed.
    """
    try:
        # Smart GitHub URL conversion (similar to repository.py)
        if "github.com" in repo_url and "raw.githubusercontent.com" not in repo_url:
            try:
                clean_url = repo_url.replace(".git", "").rstrip('/')
                parts = clean_url.split('/')
                if len(parts) >= 5:
                    user = parts[3]
                    repo = parts[4]
                    # Default to master/main if not specified
                    repo_url = f"https://raw.githubusercontent.com/{user}/{repo}/master/"
            except Exception as e:
                log_to_file(f"GitHub URL conversion failed: {e}")

        # Ensure the URL ends with a forward slash
        if not repo_url.endswith('/'):
            repo_url += '/'

        # Try common paths for addons.xml
        candidates = ["addons.xml", "zips/addons.xml", "addon.xml"]
        response = None
        
        for candidate in candidates:
            try:
                r = requests.get(f"{repo_url}{candidate}", timeout=15)
                if r.status_code == 200:
                    response = r
                    break
            except requests.exceptions.RequestException:
                continue

        if not response:
            raise Exception(f"Could not find addons.xml in {repo_url} (checked: {candidates})")

        # Parse directly from bytes to let ElementTree handle encoding (utf-8, iso-8859-1, etc.)
        root = ET.fromstring(response.content)
        
        for addon in root.findall('addon'):
            addon_id = addon.get('id')
            version = addon.get('version')
            name = addon.get('name')

            addon_path = os.path.join(addons_dir, addon_id)
            local_addon_xml_path = os.path.join(addon_path, 'addon.xml')

            if os.path.exists(addon_path) and os.path.exists(local_addon_xml_path):
                try:
                    tree = ET.parse(local_addon_xml_path)
                    local_root = tree.getroot()

                    # Update addon information
                    local_root.set('version', version)
                    local_root.set('name', name)

                    # Write the changes back to the file
                    tree.write(local_addon_xml_path, encoding='utf-8', xml_declaration=True)
                    log_to_file(f"Updated {addon_id} in {local_addon_xml_path}")

                except Exception as e:
                    log_to_file(f"Error updating {addon_id}: {e}")
            else:
                log_to_file(f"Addon {addon_id} not found locally.")

        log_to_file("Addons update process completed.")

    except requests.exceptions.RequestException as e:
        log_to_file(f"Failed to fetch addons.xml from {repo_url}: {e}")
    except ET.ParseError as e:
        log_to_file(f"Failed to parse addons.xml: {e}")
    except Exception as e:
        log_to_file(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    # Example usage:
    repo_url = "https://vikingskoditeam.github.io/"  # Replace with your repository URL
    addons_dir = "data/addons"  # Replace with your addons directory
    
    # Ensure addons_dir is an absolute path
    addons_dir = os.path.abspath(addons_dir)

    fetch_and_update_addons_xml(repo_url, addons_dir)