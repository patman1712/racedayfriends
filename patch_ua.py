import os
import glob

site_packages = "/Users/foto-scheiber/Library/Python/3.9/lib/python/site-packages"
client_file = os.path.join(site_packages, "iracingdataapi", "client.py")

print(f"Patche User-Agent in: {client_file}")

with open(client_file, 'r') as f:
    content = f.read()

# Suche nach der Stelle wo Session erstellt wird
# In 1.4.2 ist es in __init__
old_code = "self.session = requests.Session()"
new_code = """self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})"""

if old_code in content and "Mozilla/5.0" not in content:
    content = content.replace(old_code, new_code)
    print("Patch angewendet!")
    with open(client_file, 'w') as f:
        f.write(content)
else:
    print("Patch nicht nötig oder Code nicht gefunden.")
