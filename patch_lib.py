import os
import re
import glob

# Pfad zu den installierten Paketen
site_packages = "/Users/foto-scheiber/Library/Python/3.9/lib/python/site-packages"
models_dir = os.path.join(site_packages, "iracingdataapi", "models")

print(f"Suche in: {models_dir}")

files = glob.glob(os.path.join(models_dir, "*.py"))

for file_path in files:
    print(f"Verarbeite {os.path.basename(file_path)}...")
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check if we need to patch
    if "| None" not in content and "None |" not in content:
        continue
        
    # Add import if missing
    if "from typing import Optional" not in content:
        if "from typing import" in content:
             content = content.replace("from typing import", "from typing import Optional,")
        else:
             content = "from typing import Optional\n" + content

    # Replace "Type | None" with "Optional[Type]"
    # Pattern: capture the type before " | None"
    # Be careful with nested types.
    # Simple types: \w+ | None
    content = re.sub(r'(\w+)\s*\|\s*None', r'Optional[\1]', content)
    content = re.sub(r'None\s*\|\s*(\w+)', r'Optional[\1]', content)
    
    # Generic types: list[str] | None
    # This is harder with regex.
    # Let's try a few common patterns.
    content = re.sub(r'(list\[[^\]]+\])\s*\|\s*None', r'Optional[\1]', content)
    content = re.sub(r'(dict\[[^\]]+\])\s*\|\s*None', r'Optional[\1]', content)
    
    # Write back
    with open(file_path, 'w') as f:
        f.write(content)
        
print("Fertig gepatcht!")
