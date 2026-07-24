"""Inline keyboards used by the API-backed Telegram frontend."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_markup(profile_name: str | None = None) -> InlineKeyboardMarkup:
    profile_label = f"Profile: {profile_name}" if profile_name else "Profiles"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(profile_label[:60], callback_data="profile:info")],
            [InlineKeyboardButton("Pilih worker", callback_data="worker:info")],
            [InlineKeyboardButton("Utility", callback_data="utility:menu")],
            [InlineKeyboardButton("Storage channel", callback_data="storage:menu")],
            [InlineKeyboardButton("Backup terenkripsi", callback_data="backup:menu")],
            [
                InlineKeyboardButton(
                    "Export dari source tersimpan", callback_data="sources:0"
                )
            ],
            [InlineKeyboardButton("Jalankan /download", callback_data="menu:download")],
            [InlineKeyboardButton("Status download", callback_data="menu:status")],
            [
                InlineKeyboardButton(
                    "Pengaturan download", callback_data="download:settings"
                )
            ],
            [
                InlineKeyboardButton("Retry failed", callback_data="menu:retry"),
                InlineKeyboardButton(
                    "Clear failed", callback_data="menu:clear_confirm"
                ),
            ],
            [InlineKeyboardButton("Cancel download", callback_data="menu:cancel")],
            [InlineKeyboardButton("Help", callback_data="menu:help")],
        ]
    )


def storage_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Upload", callback_data="storage:upload")],
            [InlineKeyboardButton("Cari file", callback_data="storage:search")],
            [InlineKeyboardButton("Kelola file saya", callback_data="storage:mine")],
            [
                InlineKeyboardButton(
                    "Pengaturan channel", callback_data="storage:settings"
                )
            ],
            [InlineKeyboardButton("Menu utama", callback_data="menu:main")],
        ]
    )


def storage_folders_markup(folders: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                folder[-60:], callback_data=f"storage:folder:{index}"
            )
        ]
        for index, folder in enumerate(folders)
    ]
    rows.append([InlineKeyboardButton("Kembali", callback_data="storage:menu")])
    return InlineKeyboardMarkup(rows)


def storage_item_markup(
    item_id: int, owner: bool = True
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                "Download", callback_data=f"storage:download:{item_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "Detail", callback_data=f"storage:detail:{item_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "Rename metadata", callback_data=f"storage:rename:{item_id}"
            )
        ],
    ]
    if owner:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "Edit folder",
                        callback_data=f"storage:folder_edit:{item_id}",
                    ),
                    InlineKeyboardButton(
                        "Edit keyword",
                        callback_data=f"storage:keyword_edit:{item_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Hapus", callback_data=f"storage:delete:{item_id}"
                    )
                ],
            ]
        )
    rows.append(
        [InlineKeyboardButton("Kembali storage", callback_data="storage:menu")]
    )
    return InlineKeyboardMarkup(rows)


def storage_delete_markup(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, hapus message",
                    callback_data=f"storage:delete_yes:{item_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Batal", callback_data=f"storage:detail:{item_id}"
                )
            ],
        ]
    )


def backup_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Backup sekarang", callback_data="backup:now")],
            [InlineKeyboardButton("Status backup", callback_data="backup:status")],
            [InlineKeyboardButton("Daftar backup", callback_data="backup:list")],
            [
                InlineKeyboardButton(
                    "Pengaturan backup", callback_data="backup:settings"
                )
            ],
            [InlineKeyboardButton("Menu utama", callback_data="menu:main")],
        ]
    )


def worker_menu_markup(
    profile_name: str, selected: str, routes: list[str]
) -> InlineKeyboardMarkup:
    del profile_name
    labels = {
        "local": "VPS utama / worker lokal",
        "remote": "VPS kedua / worker remote",
    }
    rows = [
        [
            InlineKeyboardButton(
                (("* " if route == selected else "") + labels.get(route, route))[
                    :60
                ],
                callback_data=f"worker:set:{route}",
            )
        ]
        for route in routes
    ]
    rows.append([InlineKeyboardButton("Kembali", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def check_profile_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Check Profile", callback_data="access:check")]]
    )


def utility_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Extract", callback_data="utility:folders:extract")],
            [
                InlineKeyboardButton(
                    "Compress", callback_data="utility:folders:compress"
                )
            ],
            [InlineKeyboardButton("Export", callback_data="utility:folders:export")],
            [InlineKeyboardButton("Pindah", callback_data="utility:folders:pindah")],
            [
                InlineKeyboardButton(
                    "Pengaturan default", callback_data="utility:settings"
                )
            ],
            [InlineKeyboardButton("Menu utama", callback_data="menu:main")],
        ]
    )


def utility_settings_markup(settings: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Ukuran pindah: {settings['move_size']}",
                    callback_data="utility:setting:move_size",
                )
            ],
            [
                InlineKeyboardButton(
                    f"Ukuran compress: {settings['compress_size']}",
                    callback_data="utility:setting:compress_size",
                )
            ],
            [
                InlineKeyboardButton(
                    "Ubah password compress",
                    callback_data="utility:setting:compress_password",
                )
            ],
            [InlineKeyboardButton("Kembali", callback_data="utility:menu")],
        ]
    )


def utility_folders_markup(
    utility: str, folders: list[str], selected: set[str]
) -> InlineKeyboardMarkup:
    rows = []
    for index, folder in enumerate(folders):
        label = ("[x] " if folder in selected else "[ ] ") + folder
        rows.append(
            [
                InlineKeyboardButton(
                    label[-60:],
                    callback_data=f"utility:select:{utility}:{index}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Pilih semua", callback_data=f"utility:all:{utility}"
            ),
            InlineKeyboardButton("Reset", callback_data=f"utility:clear:{utility}"),
        ]
    )
    if selected:
        rows.append(
            [
                InlineKeyboardButton(
                    f"Jalankan ({len(selected)})",
                    callback_data=f"utility:ask:{utility}",
                ),
                InlineKeyboardButton(
                    "Hapus folder", callback_data=f"utility:remove:{utility}"
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Tambah custom", callback_data=f"utility:add:{utility}"
            )
        ]
    )
    rows.append([InlineKeyboardButton("Kembali", callback_data="utility:menu")])
    return InlineKeyboardMarkup(rows)


def utility_confirm_markup(utility: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, jalankan", callback_data=f"utility:run:{utility}"
                )
            ],
            [
                InlineKeyboardButton(
                    "Batal", callback_data=f"utility:folders:{utility}"
                )
            ],
        ]
    )


def download_status_markup(done: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Refresh status", callback_data="status:refresh")]
    ]
    if not done:
        rows.append(
            [InlineKeyboardButton("Cancel download", callback_data="menu:cancel")]
        )
    rows.append([InlineKeyboardButton("Menu utama", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def clear_confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, hapus semua failed", callback_data="menu:clear_yes"
                )
            ],
            [InlineKeyboardButton("Batal", callback_data="menu:main")],
        ]
    )
