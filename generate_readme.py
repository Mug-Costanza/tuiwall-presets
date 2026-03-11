import os
import re

def parse_metadata(file_path):
    ALLOWED_CATEGORIES = ["Animation", "Dashboard", "Ambiance", "System", "Productivity", "Misc"]
    metadata = {"Name": "Unknown", "Author": "Unknown", "Category": "Misc", "Description": "No description provided."}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(1024)
            for line in content.split('\n'):
                if line.startswith('#'):
                    clean = line.lstrip('#').strip()
                    if ':' in clean:
                        key, val = clean.split(':', 1)
                        key = key.strip().capitalize()
                        if key in metadata:
                            value = val.strip()
                            if key == "Category" and value not in ALLOWED_CATEGORIES:
                                value = "Misc"
                            metadata[key] = value
    except Exception:
        pass
    return metadata

def generate_organized_content():
    preset_dir = "presets"
    image_dir = "images" # Folder where thumbnails are stored
    sections = {}
    
    if not os.path.exists(preset_dir):
        return "No presets found."

    for root, dirs, files in os.walk(preset_dir):
        for file in files:
            if file.endswith(".py"):
                name = os.path.splitext(file)[0]
                meta = parse_metadata(os.path.join(root, file))
                
                cat = meta['Category']
                if cat not in sections:
                    sections[cat] = []
                
                repo_url = f"https://github.com/Mug-Costanza/tuiwall-presets/tree/main/presets/{name}"
                img_src = f"https://raw.githubusercontent.com/Mug-Costanza/tuiwall-presets/main/images/{name}.png"
                
                # Check if an image exists locally to decide if we use a thumbnail
                local_img = os.path.join(image_dir, f"{name}.png")
                
                if os.path.exists(local_img):
                    # HTML-style centering and sizing for the thumbnail
                    entry = (
                        f"| [![{meta['Name']}]({img_src})]({repo_url}) |\n"
                        f"| :--- |\n"
                        f"| **{meta['Name']}** - {meta['Description']} |\n\n"
                    )
                else:
                    entry = f"* [{meta['Name']}]({repo_url}) - {meta['Description']} (No Preview)\n"
                
                sections[cat].append(entry)
    
    output = ["## Table of Contents"]
    for cat in sorted(sections.keys()):
        anchor = cat.lower().replace(" ", "-")
        output.append(f"* [{cat}](#{anchor})")
    
    output.append("\n---")
    
    for cat in sorted(sections.keys()):
        output.append(f"\n### {cat}")
        output.append("<details><summary>Click to view gallery</summary>\n")
        # For categories with images, a grid layout looks best
        for entry in sorted(sections[cat]):
            output.append(entry)
        output.append("\n</details>")
    
    return "\n".join(output)

def update_readme(content):
    marker_start = "# TUIWALL PRESETS"
    marker_end = "# End of List"
    
    if not os.path.exists("README.md"):
        return

    with open("README.md", "r", encoding='utf-8') as f:
        full_text = f.read()

    if marker_start not in full_text or marker_end not in full_text:
        return

    pattern = f"{re.escape(marker_start)}.*?{re.escape(marker_end)}"
    replacement = f"{marker_start}\n\n{content}\n\n{marker_end}"
    
    new_content = re.sub(pattern, replacement, full_text, flags=re.DOTALL)
    
    with open("README.md", "w", encoding='utf-8') as f:
        f.write(new_content)

if __name__ == "__main__":
    update_readme(generate_organized_content())
