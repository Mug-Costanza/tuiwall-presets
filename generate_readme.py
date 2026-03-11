import os
import re

def parse_metadata(file_path):
    # The allowed categories you specified
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
                            # Validation logic for Categories
                            if key == "Category":
                                if value not in ALLOWED_CATEGORIES:
                                    value = "Misc"
                            metadata[key] = value
    except Exception:
        pass
    return metadata

def generate_organized_content():
    preset_dir = "presets"
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
                entry = f"* [{meta['Name']}]({repo_url}) - {meta['Description']}\n"
                sections[cat].append(entry)
    
    output = ["## Table of Contents"]
    for cat in sorted(sections.keys()):
        anchor = cat.lower().replace(" ", "-")
        output.append(f"* [{cat}](#{anchor})")
    
    output.append("\n---")
    
    for cat in sorted(sections.keys()):
        output.append(f"\n### {cat}")
        output.append("<details><summary>Click to view presets</summary>\n")
        for entry in sorted(sections[cat]):
            output.append(entry)
        output.append("\n</details>")
    
    return "\n".join(output)

def update_readme(content):
    # Markers set as requested
    marker_start = "# TUIWALL PRESETS"
    marker_end = "# End of List"
    
    if not os.path.exists("README.md"):
        print("Error: README.md not found.")
        return

    with open("README.md", "r", encoding='utf-8') as f:
        full_text = f.read()

    if marker_start not in full_text or marker_end not in full_text:
        print(f"Error: Markers '{marker_start}' or '{marker_end}' not found!")
        return

    # Escaping to ensure # and <> don't mess with regex logic
    pattern = f"{re.escape(marker_start)}.*?{re.escape(marker_end)}"
    replacement = f"{marker_start}\n\n{content}\n\n{marker_end}"
    
    new_content = re.sub(pattern, replacement, full_text, flags=re.DOTALL)
    
    with open("README.md", "w", encoding='utf-8') as f:
        f.write(new_content)
    print("README.md updated successfully!")

if __name__ == "__main__":
    organized_data = generate_organized_content()
    update_readme(organized_data)
