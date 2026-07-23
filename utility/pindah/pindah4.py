import os
import json
import sys

# Batas maksimal ukuran folder dalam bytes (4 GB)
MAX_SIZE = 4 * 1024 * 1024 * 1024
excluded = ['pindah2.py','pindah.py','pindah4.py','pindah.sh', 'tes.sh','new_output.json','output.json','extract.py']

def get_size(path):
    """Menghitung ukuran total dari file atau folder."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    elif os.path.isdir(path):
        total_size = 0
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            total_size += get_size(item_path)
        return total_size
    return 0

def main():
    if len(sys.argv) > 1:
        current_dir = sys.argv[1]  # Ambil direktori dari argumen pertama
    else:
        current_dir = os.getcwd()
    
    # Menghitung ukuran semua file dan folder sekali saja
    items = []
    for item in os.listdir(current_dir):
        if item not in excluded:
            item_path = os.path.join(current_dir, item)
            item_size = get_size(item_path)
            if item_size <= MAX_SIZE:
                items.append((item_path, item_size))
    
    folder_count = 1
    current_folder_size = 0
    groups = {f'group_{folder_count}': {'items': [], 'total_size': 0}}

    for item_path, item_size in items:
        if current_folder_size + item_size > MAX_SIZE:
            groups[f'group_{folder_count}']['total_size'] = current_folder_size / (1024 * 1024 * 1024)  # Convert size to GB
            folder_count += 1
            current_folder_size = 0
            groups[f'group_{folder_count}'] = {'items': [], 'total_size': 0}

        groups[f'group_{folder_count}']['items'].append({
            'file': item_path,
            'size': item_size / (1024 * 1024 * 1024)  # Convert size to GB
        })
        current_folder_size += item_size

    # Update total size for the last group
    groups[f'group_{folder_count}']['total_size'] = current_folder_size / (1024 * 1024 * 1024)

    # Export hasil ke output.json
    with open('output.json', 'w') as f:
        json.dump(groups, f, indent=4)

    print(f'File dan folder telah dikelompokkan ke dalam {folder_count} grup dan diekspor ke output.json.')

if __name__ == '__main__':
    main()
