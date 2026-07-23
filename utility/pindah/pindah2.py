import os
import json
import sys
import shutil

# Baca file JSON
with open('new_output.json', 'r') as f:
    data = json.load(f)

# Loop melalui masing-masing group dalam JSON
for group_name, group_data in data.items():
    # Buat folder baru sesuai nama group jika belum ada
    if len(sys.argv) > 1:
        current_dir = sys.argv[1]  # Ambil direktori dari argumen pertama
    else:
        current_dir = os.getcwd()
    
    folder_path = os.path.join(current_dir, group_name)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    
    # Loop melalui items dalam group
    for item in group_data['items']:
        source_file = item['file']  # Ambil path file dari item
        # Pastikan file ada sebelum dipindahkan
        if os.path.exists(source_file):
            # Pindahkan file ke folder baru
            destination_file = os.path.join(folder_path, os.path.basename(source_file))
            shutil.move(source_file, destination_file)
            print(f"Memindahkan {source_file} ke {destination_file}")
        else:
            print(f"File tidak ditemukan: {source_file}")
