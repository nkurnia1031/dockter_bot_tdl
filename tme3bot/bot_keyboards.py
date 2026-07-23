from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from tme3bot.bot_text import format_source_button, source_digest
from tme3bot.labels import SavedLabel, label_digest
from tme3bot.names import normalize_profile_name
from tme3bot.profiles import (
    DOWNLOAD_MODE_ISOLATED,
    DOWNLOAD_MODE_SHARED,
    ProfileManager,
)
from tme3bot.state import SourceState

SOURCE_PAGE_SIZE = 8


def profiles_menu_markup(
    profiles: list[str], active_profile: str
) -> InlineKeyboardMarkup:
    rows = []
    for profile in profiles[:20]:
        prefix = "* " if profile == active_profile else ""
        rows.append(
            [
                InlineKeyboardButton(
                    (prefix + profile)[:60], callback_data=f"profile:select:{profile}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("Menu utama", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def download_settings_markup(
    profile_name: str, profile_manager: ProfileManager
) -> InlineKeyboardMarkup:
    mode = profile_manager.download_mode(profile_name)
    rows = [
        [
            InlineKeyboardButton(
                ("* " if mode == DOWNLOAD_MODE_SHARED else "") + "Pakai download utama",
                callback_data=f"download:mode:{DOWNLOAD_MODE_SHARED}",
            )
        ],
    ]
    if normalize_profile_name(profile_name) != profile_manager.default_profile:
        rows.append(
            [
                InlineKeyboardButton(
                    ("* " if mode == DOWNLOAD_MODE_ISOLATED else "")
                    + "Pisahkan profile ini",
                    callback_data=f"download:mode:{DOWNLOAD_MODE_ISOLATED}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Menu utama", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def main_menu_markup(profile_name: str | None = None) -> InlineKeyboardMarkup:
    profile_label = f"Profile: {profile_name}" if profile_name else "Profiles"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(profile_label[:60], callback_data="profile:info")],
            [InlineKeyboardButton("Utility", callback_data="utility:menu")],
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


def check_profile_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Check Profile", callback_data="access:check")]]
    )


def utility_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Extract", callback_data="utility:folders:extract")],
        [InlineKeyboardButton("Compress", callback_data="utility:folders:compress")],
        [InlineKeyboardButton("Export", callback_data="utility:folders:export")],
        [InlineKeyboardButton("Pindah", callback_data="utility:folders:pindah")],
        [InlineKeyboardButton("Menu utama", callback_data="menu:main")],
    ])


def utility_folders_markup(utility: str, folders: list[str], selected: set[str]) -> InlineKeyboardMarkup:
    rows = []
    for index, folder in enumerate(folders):
        label = ("[x] " if folder in selected else "[ ] ") + folder
        rows.append([InlineKeyboardButton(label[-60:], callback_data=f"utility:select:{utility}:{index}")])
    rows.append([
        InlineKeyboardButton("Pilih semua", callback_data=f"utility:all:{utility}"),
        InlineKeyboardButton("Reset", callback_data=f"utility:clear:{utility}"),
    ])
    if selected:
        rows.append([
            InlineKeyboardButton(f"Jalankan ({len(selected)})", callback_data=f"utility:ask:{utility}"),
            InlineKeyboardButton("Hapus folder", callback_data=f"utility:remove:{utility}"),
        ])
    rows.append([InlineKeyboardButton("Tambah custom", callback_data=f"utility:add:{utility}")])
    rows.append([InlineKeyboardButton("Kembali", callback_data="utility:menu")])
    return InlineKeyboardMarkup(rows)


def utility_confirm_markup(utility: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ya, jalankan", callback_data=f"utility:run:{utility}")],
        [InlineKeyboardButton("Batal", callback_data=f"utility:folders:{utility}")],
    ])


def utility_password_markup(action: str) -> InlineKeyboardMarkup:
    if action == "extract":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Pakai nama folder", callback_data="utility:default:extract")],
            [InlineKeyboardButton("Kirim password custom", callback_data="utility:password:extract")],
            [InlineKeyboardButton("Batal", callback_data="utility:cancel:extract")],
        ])
    return InlineKeyboardMarkup([[InlineKeyboardButton("Batal", callback_data=f"utility:cancel:{action}")]])


def download_status_markup(done: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Refresh status", callback_data="status:refresh")]]
    if not done:
        rows.append(
            [InlineKeyboardButton("Cancel download", callback_data="menu:cancel")]
        )
    rows.append([InlineKeyboardButton("Menu utama", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def label_prompt_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Batal label", callback_data="menu:main")]]
    )


def sources_menu_markup(
    sources: list[tuple[str, SourceState]], page: int, selected: set[str] | None = None
) -> InlineKeyboardMarkup:
    selected = selected or set()
    page = max(page, 0)
    total_pages = max((len(sources) - 1) // SOURCE_PAGE_SIZE + 1, 1)
    page = min(page, total_pages - 1)
    start = page * SOURCE_PAGE_SIZE
    rows = []
    for chat_ref, source in sources[start : start + SOURCE_PAGE_SIZE]:
        digest = source_digest(chat_ref)
        rows.append(
            [
                InlineKeyboardButton(
                    "[x]" if chat_ref in selected else "[ ]",
                    callback_data=f"srcsel:{digest}:{page}",
                ),
                InlineKeyboardButton(
                    format_source_button(chat_ref, source),
                    callback_data=f"src:{digest}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("Pilih semua", callback_data=f"srcbatch:all:{page}"),
            InlineKeyboardButton("Reset", callback_data=f"srcbatch:clear:{page}"),
        ]
    )
    if selected:
        rows.append(
            [
                InlineKeyboardButton(
                    f"Hapus terpilih ({len(selected)})",
                    callback_data=f"srcbatch:ask:{page}",
                ),
                InlineKeyboardButton(
                    f"Leave terpilih ({len(selected)})",
                    callback_data=f"srcbatch:leave:{page}",
                ),
            ]
        )
    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton("Prev", callback_data=f"sources:{page - 1}")
        )
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton("Next", callback_data=f"sources:{page + 1}")
        )
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("Kembali", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def source_detail_markup(
    chat_ref: str, source: SourceState, saved_labels: list[SavedLabel] | None = None
) -> InlineKeyboardMarkup:
    digest = source_digest(chat_ref)
    rows = []
    if source.label:
        rows.append(
            [
                InlineKeyboardButton(
                    f"Export dengan label terakhir: {source.label}"[:60],
                    callback_data=f"export:{digest}:label",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Export tanpa label", callback_data=f"export:{digest}:plain"
            )
        ]
    )

    seen = {source.label} if source.label else set()
    for item in saved_labels or []:
        if item.label in seen:
            continue
        seen.add(item.label)
        rows.append(
            [
                InlineKeyboardButton(
                    f"Label: {item.label}"[:60],
                    callback_data=f"export:{digest}:saved:{label_digest(item.label)}",
                )
            ]
        )
        if len(rows) >= 10:
            break

    rows.append(
        [
            InlineKeyboardButton(
                "Ketik label custom", callback_data=f"export:{digest}:custom"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "Hapus source / Last ID", callback_data=f"srcdel:{digest}:ask"
            )
        ]
    )
    rows.append([InlineKeyboardButton("Kembali ke source", callback_data="sources:0")])
    return InlineKeyboardMarkup(rows)


def delete_source_confirm_markup(digest: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, hapus source", callback_data=f"srcdel:{digest}:yes"
                )
            ],
            [InlineKeyboardButton("Batal", callback_data=f"src:{digest}")],
        ]
    )


def batch_delete_source_confirm_markup(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, hapus semua terpilih", callback_data=f"srcbatch:yes:{page}"
                )
            ],
            [InlineKeyboardButton("Batal", callback_data=f"sources:{page}")],
        ]
    )


def batch_leave_source_confirm_markup(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Ya, leave semua terpilih", callback_data=f"srcbatch:leave_yes:{page}")],
            [InlineKeyboardButton("Batal", callback_data=f"sources:{page}")],
        ]
    )


def clear_confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Ya, hapus failed", callback_data="menu:clear_yes")],
            [InlineKeyboardButton("Batal", callback_data="menu:main")],
        ]
    )
