import os
import re
import argparse
import subprocess
import json


def emit_progress(**values):
    print('TME3_PROGRESS ' + json.dumps(values, ensure_ascii=True), flush=True)


def get_folder_password(folder):
    abs_folder = os.path.abspath(folder)
    name = os.path.basename(abs_folder)
    return name if name else abs_folder


# =============================
# MULTIPART DETECTION
# =============================
def get_multipart_group(filepath):
    folder = os.path.dirname(filepath)
    filename = os.path.basename(filepath)

    rar_match = re.match(r'(.+)\.part\d+\.rar$', filename, re.IGNORECASE)
    if rar_match:
        base = rar_match.group(1)
        return [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().startswith(base.lower()) and (
                re.search(r'\.part\d+\.rar$', f.lower()) or
                re.search(r'\.r\d+$', f.lower())
            )
        ]

    if re.match(r'.+\.r\d+$', filename.lower()):
        base = re.sub(r'\.r\d+$', '', filename, flags=re.IGNORECASE)
        return [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().startswith(base.lower())
        ]

    seven_match = re.match(r'(.+\.7z)\.\d+$', filename, re.IGNORECASE)
    if seven_match:
        base = seven_match.group(1)
        return [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().startswith(base.lower() + '.')
        ]

    zip_match = re.match(r'(.+)\.zip$', filename, re.IGNORECASE)
    if zip_match:
        base = zip_match.group(1)
        parts = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().startswith(base.lower()) and (
                f.lower().endswith('.zip') or re.search(r'\.z\d+$', f.lower())
            )
        ]
        return parts if len(parts) > 1 else [filepath]

    return [filepath]


def is_main_part(filename):
    lower = filename.lower()

    # Untuk RAR multipart, cukup proses volume pertama. Pengecekan ini harus
    # dilakukan sebelum endswith('.rar') agar part2, part3, dst. tidak ikut.
    if re.match(r'.+\.part\d+\.rar$', lower):
        return bool(re.match(r'.+\.part0*1\.rar$', lower))

    return (
        lower.endswith('.7z') or
        lower.endswith('.zip') or
        lower.endswith('.rar') or
        lower.endswith('.7z.001')
    )


def get_extract_folder_name(filename):
    part_rar_match = re.match(r'(.+)\.part\d+\.rar$', filename, re.IGNORECASE)
    if part_rar_match:
        return os.path.basename(part_rar_match.group(1))

    seven_part_match = re.match(r'(.+)\.7z\.\d+$', filename, re.IGNORECASE)
    if seven_part_match:
        return os.path.basename(seven_part_match.group(1))

    return os.path.splitext(filename)[0]


# =============================
# RUN COMMAND
# =============================
def run_extract(cmd, folder):
    result = subprocess.run(cmd, cwd=folder)
    return result.returncode == 0


def cleanup_empty_directory(path):
    if not os.path.isdir(path):
        return False

    try:
        if not os.listdir(path):
            os.rmdir(path)
            return True
    except Exception as e:
        print(f'[!] Gagal hapus folder kosong {path}: {e}')

    return False


# =============================
# INTERACTIVE PASSWORD LOOP
# =============================
def try_extract_with_prompt(filepath, cmd_builder, default_password, allow_prompt=True):
    folder = os.path.abspath(os.path.dirname(filepath) or '.')
    filename = os.path.basename(filepath)

    password = default_password
    tried = set()
    tried_dot_pass = False  # Flag agar file .pass hanya dicoba sekali

    while True:
        cmd = cmd_builder(password)

        print('=' * 60)
        print(f'[+] Extracting : {filename}')
        print('[+] Password   : [REDACTED]')
        print('-' * 60)

        success = run_extract(cmd, folder)

        if success:
            return True

        print('[x] Password salah / extract gagal')

        tried.add(password)

        # ===== CEK FILE .pass =====
        pass_file = os.path.join(folder, '.pass')
        if not tried_dot_pass and os.path.isfile(pass_file):
            tried_dot_pass = True
            try:
                with open(pass_file, 'r', encoding='utf-8') as f:
                    dot_password = f.read().strip()

                # Pastikan password dari .pass tidak kosong dan belum pernah dicoba
                if dot_password and dot_password not in tried:
                    print('[!] Menemukan file .pass, mencoba password tersimpan.')
                    password = dot_password
                    continue
            except Exception as e:
                print(f'[!] Gagal membaca file .pass: {e}')

        # ===== USER INPUT =====
        if not allow_prompt:
            return False
        new_pass = input('[?] Masukkan password baru (kosong = skip): ').strip()

        if not new_pass:
            print('[!] Skip archive ini')
            return False

        if new_pass in tried:
            print('[!] Password sudah dicoba')
            continue

        password = new_pass


# =============================
# EXTRACTION
# =============================
def extract_archive(filepath, password=None, allow_prompt=True, index=1, total=1):
    filepath = os.path.abspath(filepath)
    folder = os.path.dirname(filepath)
    filename = os.path.basename(filepath)

    if not is_main_part(filename):
        print(f'[!] Skip non-main part: {filename}')
        return

    if password is None:
        password = get_folder_password(folder)

    lower = filename.lower()

    base_name = get_extract_folder_name(filename)
    extract_dir = os.path.join(folder, base_name)
    extract_dir_preexisting = os.path.isdir(extract_dir)
    emit_progress(
        phase='extracting',
        index=index,
        total=total,
        name=filename,
        indeterminate=lower.endswith('.rar'),
    )

    if lower.endswith(('.7z', '.7z.001', '.zip')):
        def builder(p):
            return [
                '7z', 'x',
                f'-p{p}',
                '-y',
                filepath,
                f'-o{extract_dir}'
                , '-bsp1'
            ]

    elif lower.endswith('.rar'):
        def builder(p):
            return [
                'unar',
                '-force-overwrite',
                '-no-directory',
                '-password', p,
                '-output-directory', extract_dir,
                filepath
            ]

    else:
        return

    success = try_extract_with_prompt(filepath, builder, password, allow_prompt)

    if success:
        print('[OK] Extract berhasil')

        parts = get_multipart_group(filepath)

        for part in parts:
            try:
                os.remove(part)
                print(f'[OK] Hapus: {os.path.basename(part)}')
            except Exception as e:
                print(f'[!] Gagal hapus {part}: {e}')
    elif not extract_dir_preexisting:
        cleanup_empty_directory(extract_dir)
    emit_progress(
        phase='item_completed' if success else 'item_failed',
        index=index,
        total=total,
        name=filename,
        percent=100 if success else None,
        indeterminate=False,
    )
    return success


# =============================
# SCAN
# =============================
def scan_directory(base_dir, password, allow_prompt=True):
    base_dir = os.path.abspath(base_dir)
    success = True
    archives = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if is_main_part(file):
                filepath = os.path.join(root, file)
                archives.append(filepath)
    total = len(archives)
    for index, filepath in enumerate(archives, start=1):
        # Daftar arsip adalah snapshot. Arsip mungkin sudah terhapus sebagai
        # bagian dari grup multipart yang baru selesai diproses.
        if os.path.isfile(filepath):
            success = extract_archive(
                filepath, password, allow_prompt, index=index, total=total
            ) and success
    return success


# =============================
# MAIN
# =============================
def main():
    parser = argparse.ArgumentParser(description='Auto Extract (Interactive Password)')
    parser.add_argument('dir', nargs='?', default='.')
    parser.add_argument('-p', '--password')
    parser.add_argument('--no-prompt', action='store_true')

    args = parser.parse_args()
    return 0 if scan_directory(args.dir, args.password, not args.no_prompt) else 1


if __name__ == '__main__':
    main()
