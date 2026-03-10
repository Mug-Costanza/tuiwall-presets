import os
import re

def parse_metadata(file_path):
    metadata = {"Name": "Unknown", "Author": "Unknown", "Category": "Misc", "Description": "No description provided."}
    try:
        with open(file_path, 'r') as f:
            content = f.read(1024)
            for line in content.split('\n'):
                if line.startswith('#'):
                    clean = line.lstrip('#').strip()
                    if ':' in clean:
                        key, val = clean.split(':', 1)
                        key = key.strip().capitalize()
                        if key in metadata:
                            metadata[key] = val.strip()
    except Exception:
        pass
    return metadata

def generate_table():
    preset_dir = "presets"
    rows = ["| Command | Preset | Author | Category | Description |", "| :--- | :--- | :--- | :--- | :--- |"]
    
    for root, dirs, files in os.walk(preset_dir):
        for file in files:
            if file.endswith(".py"):
                name = os.path.splitext(file)[0]
                meta = parse_metadata(os.path.join(root, file))
                cmd = f"`tuiwall install {name}`"
                rows.append(f"| {cmd} | **{meta['Name']}** | {meta['Author']} | {meta['Category']} | {meta['Description']} |")
    
    return "\n".join(rows)

def update_readme(table_content):
    with open("README.md", "r") as f:
        content = f.read()

    # Look for placeholders in your README
    marker_start = ""
    marker_end = ""
    
    pattern = f"{marker_start}.*?{marker_end}"
    replacement = f"{marker_start}\n\n{table_content}\n\n{marker_end}"
    
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    with open("README.md", "w") as f:
        f.write(new_content)

if __name__ == "__main__":
    table = generate_table()
    update_readme(table)
