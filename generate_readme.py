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
                        parts = clean.split(':', 1)
                        key = parts[0].strip().capitalize()
                        if key in metadata:
                            value = parts[1].strip()
                            if key == "Category" and value not in ALLOWED_CATEGORIES:
                                value = "Misc"
                            metadata[key] = value
    except Exception:
        pass
    return metadata

def generate_organized_content():
    preset_dir = "presets"
    image_dir = "images" 
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
                
                local_img = os.path.join(image_dir, f"{name}.png")
                
                # Installation command block for easy copying
                install_cmd = f"```bash\ntuiwall install {name}\n```"
                
                if os.path.exists(local_img):
                    # REMOVED: Nested "View Preview" dropdown
                    # The image and install command now appear together under the main preset toggle
                    entry = (
                        f"<details><summary><b>{meta['Name']}</b> - {meta['Description']}</summary>\n\n"
                        f"**Install:**\n{install_cmd}\n\n"
                        f"| [![{meta['Name']}]({img_src})]({repo_url}) |\n"
                        f"| :--- |\n"
                        f"| [View Source]({repo_url}) |\n\n"
                        f"</details>\n"
                    )
                else:
                    entry = (
                        f"<details><summary><b>{meta['Name']}</b> - {meta['Description']} (No Preview)</summary>\n\n"
                        f"**Install:**\n{install_cmd}\n\n"
                        f"[View Source]({repo_url})\n\n"
                        f"</details>\n"
                    )
                
                sections[cat].append(entry)
    
    output = ["## Table of Contents"]
    for cat in sorted(sections.keys()):
        anchor = cat.lower().replace(" ", "-")
        output.append(f"* [{cat}](#{anchor})")
    
    output.append("\n---")
    
    for cat in sorted(sections.keys()):
        output.append(f"\n### {cat}")
        output.append("<details><summary>Click to view category</summary>\n")
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
