import os
import glob

# Pfad zu den installierten Paketen
site_packages = "/Users/foto-scheiber/Library/Python/3.9/lib/python/site-packages"
models_dir = os.path.join(site_packages, "iracingdataapi", "models")
client_file = os.path.join(site_packages, "iracingdataapi", "client.py")

print(f"Suche in: {models_dir}")

files = glob.glob(os.path.join(models_dir, "*.py"))
files.append(client_file) # Patch client.py too

for file_path in files:
    print(f"Patche {os.path.basename(file_path)}...")
    with open(file_path, 'r') as f:
        content = f.read()
    
    if "from __future__ import annotations" not in content:
        content = "from __future__ import annotations\n" + content
        
    with open(file_path, 'w') as f:
        f.write(content)
        
print("Fertig mit __future__ patch!")
