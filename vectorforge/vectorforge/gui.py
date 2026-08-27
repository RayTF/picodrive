"""VectorDrive-inspired PySide6 interface for VectorForge."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from backend.artwork import convert_artwork
from backend.providers.screenscraper import ScreenScraperCredentials

from .builder import build_zip
from .iso import build_iso
from .library import Game, LibraryStore
from .package import PackageReader
from .paths import AppPaths
from .scrape import (
    ManualCandidate, apply_manual_candidate, find_manual_candidates, scrape_library,
)
from .settings import SettingsStore


def run_gui(paths: AppPaths) -> int:
    """Launch the application. Qt is imported lazily for CLI-only installs."""

    try:
        from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
        from PySide6.QtGui import (
            QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPixmap,
        )
        from PySide6.QtWidgets import (
            QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
            QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
            QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
            QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTextEdit,
            QVBoxLayout, QWidget,
        )
    except ImportError as error:
        raise RuntimeError("PySide6 is required for the VectorForge GUI") from error

    application = QApplication.instance() or QApplication([])
    forge_root = Path(__file__).resolve().parents[1]
    assets_root = forge_root / "assets"
    paths.temp.mkdir(parents=True, exist_ok=True)

    def _load_font(filename: str) -> Optional[str]:
        font_path = assets_root / filename
        if not font_path.is_file():
            return None
        identifier = QFontDatabase.addApplicationFont(str(font_path))
        if identifier < 0:
            return None
        families = QFontDatabase.applicationFontFamilies(identifier)
        return families[0] if families else None

    icon_families = {
        "solid": _load_font("fa-solid-900.otf"),
        "brands": _load_font("fa-brands-400.otf"),
    }

    ICONS = {
        "library": ("solid", 0xF07B),
        "builder": ("solid", 0xF1B2),
        "settings": ("solid", 0xF013),
        "logs": ("solid", 0xF15C),
        "about": ("solid", 0xF05A),
        "import": ("solid", 0xF56F),
        "folder": ("solid", 0xF07C),
        "scrape": ("solid", 0xF2F1),
        "search": ("solid", 0xF002),
        "edit": ("solid", 0xF044),
        "archive": ("solid", 0xF187),
        "disc": ("solid", 0xF51F),
        "plus": ("solid", 0xF067),
        "save": ("solid", 0xF0C7),
        "info": ("solid", 0xF129),
        "github": ("brands", 0xF09B),
        "website": ("solid", 0xF0AC),
    }

    def fa_icon(name: str, color: str = "#A8B0C5", size: int = 18) -> QIcon:
        family_name, codepoint = ICONS[name]
        family = icon_families.get(family_name)
        if family is None:
            return QIcon()
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QColor(color))
        painter.setFont(QFont(family, size))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, chr(codepoint))
        painter.end()
        return QIcon(pixmap)

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.store = LibraryStore(paths.library)
            self.settings_store = SettingsStore(paths.config)
            self.settings = self.settings_store.load()
            self.base_zip: Optional[Path] = None
            self.games: list[Game] = []
            self.scrape_thread: Optional[QThread] = None
            self.scrape_worker: Optional[QObject] = None
            self.log_lines: list[str] = []
            self.setWindowTitle("VectorForge")
            self.setMinimumSize(1080, 700)
            self.resize(1280, 800)
            logo = assets_root / "icon.png"
            if logo.is_file():
                self.setWindowIcon(QIcon(str(logo)))
            self._build_shell()
            self._build_library_page()
            self._build_builder_page()
            self._build_settings_page()
            self._build_about_page()
            self._build_logs_page()
            self._load_page("library")
            self.refresh_library()
            self._log("Session started")

        def _build_shell(self) -> None:
            root = QWidget()
            root_layout = QVBoxLayout(root)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
            top = QFrame()
            top.setObjectName("topbar")
            top_layout = QHBoxLayout(top)
            top_layout.setContentsMargins(22, 14, 22, 14)
            brand_block = QWidget()
            brand_layout = QVBoxLayout(brand_block)
            brand_layout.setContentsMargins(0, 0, 0, 0)
            brand_layout.setSpacing(2)
            brand_icon = QLabel()
            brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo = assets_root / "logo.png"
            if logo.is_file():
                brand_icon.setPixmap(QPixmap(str(logo)).scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio,
                                                                 Qt.TransformationMode.SmoothTransformation))
            self.activity_status = QLabel("Ready")
            self.activity_status.setObjectName("activityStatus")
            self.activity_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            brand_layout.addWidget(brand_icon)
            brand_layout.addWidget(self.activity_status)
            top_layout.addStretch()
            top_layout.addWidget(brand_block)
            top_layout.addStretch()
            root_layout.addWidget(top)

            body = QWidget()
            body_layout = QHBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(0)
            sidebar = QFrame()
            sidebar.setObjectName("sidebar")
            sidebar.setFixedWidth(218)
            side_layout = QVBoxLayout(sidebar)
            side_layout.setContentsMargins(14, 24, 14, 18)
            side_layout.setSpacing(8)
            caption = QLabel("VECTORDRIVE TOOLS")
            caption.setObjectName("sideCaption")
            side_layout.addWidget(caption)
            self.nav_buttons: Dict[str, QPushButton] = {}
            for key, label in (("library", "Library"), ("builder", "Builder"),
                               ("settings", "Settings"), ("logs", "Logs"), ("about", "About")):
                button = QPushButton(label)
                button.setObjectName("navButton")
                button.setIcon(fa_icon(key))
                button.setIconSize(QPixmap(20, 20).size())
                button.setMinimumHeight(44)
                button.clicked.connect(lambda _checked=False, value=key: self._load_page(value))
                self.nav_buttons[key] = button
                side_layout.addWidget(button)
            side_layout.addStretch()
            footer = QLabel("VectorDrive\nCustomizer Tool")
            footer.setObjectName("sideFooter")
            side_layout.addWidget(footer)
            body_layout.addWidget(sidebar)
            self.pages = QStackedWidget()
            body_layout.addWidget(self.pages, 1)
            root_layout.addWidget(body, 1)
            self.setCentralWidget(root)
            self.setStyleSheet(self._stylesheet())

        def _stylesheet(self) -> str:
            return """
                QWidget { color: #D7DCE8; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
                QMainWindow, QWidget#page { background: #0D0F14; }
                QFrame#topbar { background: #171A22; border-bottom: 1px solid #2B3040; }
                QLabel#activityStatus { color: #9AA5B9; font-size: 11px; font-weight: 700; padding: 0 8px 3px; }
                QLabel#brand { color: #F3F5FA; font-size: 17px; font-weight: 800; letter-spacing: 2px; }
                QLabel#statusPill { background: #183C28; color: #FFFFFF; border: 1px solid #2D761E;
                    border-radius: 12px; padding: 6px 13px; font-size: 11px; font-weight: 700; }
                QFrame#sidebar { background: #11141B; border-right: 1px solid #272C38; }
                QLabel#sideCaption { color: #697287; font-size: 11px; font-weight: 700; padding: 0 10px 8px; }
                QLabel#sideFooter { color: #596174; font-size: 11px; line-height: 1.4; padding: 10px; }
                QPushButton#navButton { text-align: left; border: 0; border-radius: 8px; padding: 10px 13px;
                    color: #929AAF; background: transparent; font-weight: 600; }
                QPushButton#navButton:hover { color: #FFFFFF; background: #1B202B; }
                QPushButton#navButton[selected="true"] { color: #FFFFFF; background: #2D761E; }
                QLabel#pageTitle { color: #F4F6FA; font-size: 27px; font-weight: 800; }
                QLabel#eyebrow { color: #2D761E; font-size: 11px; font-weight: 800; letter-spacing: 1px; }
                QFrame#card { background: #171A23; border: 1px solid #2A3040; border-radius: 10px; }
                QFrame#artCard { background: #090B0F; border: 1px solid #303749; border-radius: 6px; }
                QLineEdit, QComboBox, QTextEdit, QSpinBox { background: #12151C; border: 1px solid #303748;
                    border-radius: 6px; padding: 9px; color: #E7EAF2; selection-background-color: #2D761E; }
                QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #2D761E; }
                QPushButton#primary { background: #2D761E; color: #FFFFFF; border: 0; border-radius: 6px;
                    padding: 10px 15px; font-weight: 700; }
                QPushButton#primary:hover { background: #2D761E; }
                QPushButton#secondary { background: #202531; color: #DDE2EE; border: 1px solid #343B4D;
                    border-radius: 6px; padding: 9px 14px; font-weight: 600; }
                QPushButton#secondary:hover { background: #2A3140; border-color: #4A556D; }
                QListWidget { background: #11141B; border: 1px solid #2A3040; border-radius: 8px; padding: 6px; }
                QListWidget::item { border-radius: 6px; padding: 9px; color: #B8C0D0; }
                QListWidget::item:hover { background: #1B202A; }
                QListWidget::item:selected { background: #2D761E; color: #FFFFFF; }
                QScrollArea { border: 0; background: transparent; }
                QCheckBox { color: #BFC7D8; spacing: 8px; }
                QCheckBox::indicator { width: 16px; height: 16px; }
                QLabel#fieldLabel { color: #778096; font-size: 12px; font-weight: 700; }
                QLabel#logText { color: #B5BED0; font-family: monospace; }
                QSplitter::handle { background: #252B38; }
                QTabWidget::pane { border: 0; }
            """

        def _page(self) -> tuple[QWidget, QVBoxLayout]:
            page = QWidget()
            page.setObjectName("page")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(30, 28, 34, 30)
            layout.setSpacing(18)
            self.pages.addWidget(page)
            return page, layout

        def _heading(self, layout: QVBoxLayout, eyebrow: str, title: str, detail: str) -> None:
            label = QLabel(eyebrow.upper())
            label.setObjectName("eyebrow")
            layout.addWidget(label)
            title_label = QLabel(title)
            title_label.setObjectName("pageTitle")
            layout.addWidget(title_label)
            if detail:
                subtitle = QLabel(detail)
                subtitle.setStyleSheet("color: #778096;")
                layout.addWidget(subtitle)

        def _log(self, message: str) -> None:
            line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
            self.log_lines.append(line)
            if hasattr(self, "log_output"):
                self.log_output.append(line)

        def _set_status(self, message: str) -> None:
            if hasattr(self, "activity_status"):
                self.activity_status.setText(message)
            if hasattr(self, "builder_status"):
                self.builder_status.setText(message)

        def _build_logs_page(self) -> None:
            page, layout = self._page()
            self.logs_page = page
            self._heading(layout, "Session activity", "Logs", "Everything VectorForge has done since this session started.")
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            self.log_output = QTextEdit()
            self.log_output.setObjectName("logText")
            self.log_output.setReadOnly(True)
            self.log_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            card_layout.addWidget(self.log_output, 1)
            actions = QHBoxLayout()
            clear = QPushButton("Clear Session Log")
            clear.setObjectName("secondary")
            clear.clicked.connect(self.clear_logs)
            save = QPushButton("Save Logs")
            save.setObjectName("primary")
            save.setIcon(fa_icon("save", "#FFFFFF"))
            save.clicked.connect(self.save_logs)
            actions.addWidget(clear)
            actions.addStretch()
            actions.addWidget(save)
            card_layout.addLayout(actions)
            layout.addWidget(card, 1)

        def clear_logs(self) -> None:
            self.log_lines.clear()
            self.log_output.clear()
            self._log("Session log cleared")

        def save_logs(self) -> None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save VectorForge Logs", "vectorforge-session.log",
                "Log files (*.log);;Text files (*.txt)",
            )
            if not filename:
                return
            try:
                Path(filename).write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")
                self._log(f"Saved session log to {filename}")
            except OSError as error:
                self._log(f"Failed to save session log: {error}")
                QMessageBox.critical(self, "Log save failed", str(error))

        def _build_library_page(self) -> None:
            page, layout = self._page()
            self.library_page = page
            heading = QHBoxLayout()
            title_box = QVBoxLayout()
            self._heading(title_box, "Main menu", "Game Library", "Organize, identify, and prepare your VectorDrive collection.")
            heading.addLayout(title_box)
            heading.addStretch()
            self.library_count = QLabel("0 GAMES")
            self.library_count.setObjectName("statusPill")
            heading.addWidget(self.library_count, 0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(heading)

            toolbar = QHBoxLayout()
            self.search = QLineEdit()
            self.search.setPlaceholderText("Search games, systems, publishers...")
            self.search.addAction(fa_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
            self.search.textChanged.connect(self.refresh_library)
            toolbar.addWidget(self.search, 1)
            self.system_filter = QComboBox()
            self.system_filter.addItem("All systems")
            self.system_filter.currentTextChanged.connect(self.refresh_library)
            toolbar.addWidget(self.system_filter)
            self.category_filter = QComboBox()
            self.category_filter.addItems(("All ROMs", "Main ROMs", "Extra ROMs"))
            self.category_filter.currentTextChanged.connect(self.refresh_library)
            toolbar.addWidget(self.category_filter)
            for label, icon, callback in (("Import ZIP", "import", self.import_package),
                                           ("Add Folder", "folder", self.add_folder),
                                           ("Scrape", "scrape", self.scrape)):
                button = QPushButton(label)
                button.setObjectName("secondary")
                button.setIcon(fa_icon(icon))
                button.clicked.connect(callback)
                toolbar.addWidget(button)
            layout.addLayout(toolbar)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            self.library_list = QListWidget()
            self.library_list.setIconSize(QPixmap(72, 48).size())
            self.library_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.library_list.itemSelectionChanged.connect(self._selected_game_changed)
            self.library_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.library_list.customContextMenuRequested.connect(self._show_game_context_menu)
            splitter.addWidget(self.library_list)
            self.library_detail = self._library_detail()
            splitter.addWidget(self.library_detail)
            splitter.setSizes([410, 680])
            layout.addWidget(splitter, 1)

        def _library_detail(self) -> QWidget:
            card = QFrame()
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(22, 22, 22, 22)
            self.detail_title = QLabel("Select a game")
            self.detail_title.setObjectName("pageTitle")
            self.detail_title.setWordWrap(True)
            layout.addWidget(self.detail_title)
            self.detail_subtitle = QLabel("Your selected game details appear here.")
            self.detail_subtitle.setStyleSheet("color: #7E889D;")
            layout.addWidget(self.detail_subtitle)
            art = QFrame()
            art.setObjectName("artCard")
            art_layout = QVBoxLayout(art)
            self.detail_art = QLabel("NO ARTWORK")
            self.detail_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.detail_art.setMinimumHeight(230)
            self.detail_art.setStyleSheet("color: #596174; font-size: 12px; font-weight: 700; letter-spacing: 2px;")
            art_layout.addWidget(self.detail_art)
            layout.addWidget(art)
            self.detail_meta = QLabel("")
            self.detail_meta.setWordWrap(True)
            self.detail_meta.setStyleSheet("color: #B2BBCB; line-height: 1.4;")
            layout.addWidget(self.detail_meta)
            self.detail_information = QTextEdit()
            self.detail_information.setReadOnly(True)
            self.detail_information.setMaximumHeight(110)
            self.detail_information.setPlaceholderText("No description available.")
            layout.addWidget(self.detail_information)
            actions = QHBoxLayout()
            edit = QPushButton("Edit Metadata")
            edit.setObjectName("primary")
            edit.setIcon(fa_icon("edit", "#FFFFFF"))
            edit.clicked.connect(self.edit_selected_game)
            actions.addWidget(edit)
            actions.addStretch()
            layout.addLayout(actions)
            return card

        def _build_builder_page(self) -> None:
            page, layout = self._page()
            self.builder_page = page
            self._heading(layout, "Build station", "Package Builder", "Load a VectorDrive base, then ship your library as ZIP, ISO, or both.")
            base_card = QFrame()
            base_card.setObjectName("card")
            base_layout = QVBoxLayout(base_card)
            base_layout.setContentsMargins(20, 18, 20, 18)
            base_label = QLabel("BASE PACKAGE")
            base_label.setObjectName("eyebrow")
            base_layout.addWidget(base_label)
            base_row = QHBoxLayout()
            self.base_label = QLabel("No VectorDrive ZIP loaded")
            self.base_label.setStyleSheet("color: #AAB4C7; padding: 6px;")
            base_row.addWidget(self.base_label, 1)
            choose = QPushButton("Choose Base ZIP")
            choose.setObjectName("secondary")
            choose.setIcon(fa_icon("archive"))
            choose.clicked.connect(self.choose_base)
            base_row.addWidget(choose)
            base_layout.addLayout(base_row)
            self.base_status = QLabel("No ROMs have been imported from a base package yet.")
            self.base_status.setStyleSheet("color: #667188;")
            base_layout.addWidget(self.base_status)
            layout.addWidget(base_card)

            output_card = QFrame()
            output_card.setObjectName("card")
            output_layout = QVBoxLayout(output_card)
            output_layout.setContentsMargins(20, 18, 20, 18)
            outputs_label = QLabel("BUILD OUTPUTS")
            outputs_label.setObjectName("eyebrow")
            output_layout.addWidget(outputs_label)
            output_form = QFormLayout()
            self.zip_output = QLineEdit(str(paths.projects / "VectorDrive-custom.zip"))
            self.iso_output = QLineEdit(str(paths.projects / "VectorDrive-custom.iso"))
            output_form.addRow("ZIP output", self.zip_output)
            output_form.addRow("ISO output", self.iso_output)
            output_layout.addLayout(output_form)
            layout.addWidget(output_card)
            buttons = QHBoxLayout()
            build_zip_button = QPushButton("Build ZIP")
            build_zip_button.setObjectName("primary")
            build_zip_button.setIcon(fa_icon("archive", "#FFFFFF"))
            build_zip_button.clicked.connect(self.build_package)
            build_iso_button = QPushButton("Build ISO")
            build_iso_button.setObjectName("secondary")
            build_iso_button.setIcon(fa_icon("disc"))
            build_iso_button.clicked.connect(self.build_iso_package)
            buttons.addWidget(build_zip_button)
            buttons.addWidget(build_iso_button)
            buttons.addStretch()
            layout.addLayout(buttons)
            self.builder_status = QLabel("Ready to build.")
            self.builder_status.setStyleSheet("color: #7E889D;")
            layout.addWidget(self.builder_status)
            layout.addStretch()

        def _build_settings_page(self) -> None:
            page, layout = self._page()
            self.settings_page = page
            self._heading(layout, "Application", "Settings", "Credentials and provider preferences for VectorForge.")
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 10, 0)
            content_layout.setSpacing(16)
            data_card = QFrame()
            data_card.setObjectName("card")
            data_layout = QFormLayout(data_card)
            data_layout.setContentsMargins(20, 18, 20, 18)
            data_layout.setSpacing(12)
            data_root = QLineEdit(str(paths.root))
            data_root.setReadOnly(True)
            data_layout.addRow("Data root", data_root)
            open_data = QPushButton("Open Data Folder")
            open_data.setObjectName("secondary")
            open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.root))))
            data_layout.addRow("", open_data)
            content_layout.addWidget(data_card)

            provider_card = QFrame()
            provider_card.setObjectName("card")
            form = QFormLayout(provider_card)
            form.setContentsMargins(20, 18, 20, 18)
            form.setSpacing(12)
            self.settings_fields = {}
            screen = self.settings.setdefault("screenscraper", {})
            for key, label, secret in (("dev_id", "ScreenScraper developer ID", False),
                                       ("dev_password", "ScreenScraper developer password", True),
                                       ("soft_name", "ScreenScraper software name", False),
                                       ("user", "ScreenScraper user", False), ("password", "ScreenScraper password", True)):
                field = QLineEdit(str(screen.get(key, "")))
                field.setEchoMode(QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)
                self.settings_fields[f"screenscraper.{key}"] = field
                form.addRow(label, field)
            tgdb = QLineEdit(str(self.settings.get("thegamesdb_api_key", "")))
            tgdb.setEchoMode(QLineEdit.EchoMode.Password)
            self.settings_fields["thegamesdb_api_key"] = tgdb
            form.addRow("TheGamesDB API key", tgdb)
            self.provider_checks = {}
            providers = self.settings.get("providers", ["screenscraper"])
            for provider, label in (("screenscraper", "Use ScreenScraper"), ("thegamesdb", "Use TheGamesDB")):
                check = QCheckBox(label)
                check.setChecked(provider in providers)
                self.provider_checks[provider] = check
                form.addRow(check)
            save = QPushButton("Save Settings")
            save.setObjectName("primary")
            save.setIcon(fa_icon("save", "#FFFFFF"))
            save.clicked.connect(self.save_settings)
            form.addRow(save)
            content_layout.addWidget(provider_card)
            content_layout.addStretch()
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)

        def _build_about_page(self) -> None:
            page, layout = self._page()
            self.about_page = page
            layout.addStretch(1)
            card = QFrame()
            card.setObjectName("card")
            card.setMinimumWidth(820)
            card.setMaximumWidth(912)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(65, 50, 65, 50)
            card_layout.setSpacing(16)
            logo = QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_path = assets_root / "logo.png"
            if logo_path.is_file():
                logo.setPixmap(QPixmap(str(logo_path)).scaled(240, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                                               Qt.TransformationMode.SmoothTransformation))
            card_layout.addWidget(logo)
            title = QLabel("VectorForge")
            title.setObjectName("pageTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(title)
            version = QLabel("Version 1.0.0")
            version.setAlignment(Qt.AlignmentFlag.AlignCenter)
            version.setStyleSheet("color: #2D761E;")
            card_layout.addWidget(version)
            description = QLabel("A custom library builder for VectorDrive")
            description.setAlignment(Qt.AlignmentFlag.AlignCenter)
            description.setWordWrap(True)
            description.setStyleSheet("color: #9AA5B9; font-size: 15px; padding: 12px 0;")
            card_layout.addWidget(description)
            links = QHBoxLayout()
            links.setSpacing(10)
            github = QPushButton("GitHub")
            github.setObjectName("secondary")
            github.setIcon(fa_icon("github"))
            github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/RaySollium99/VectorDrive")))
            website = QPushButton("Website")
            website.setObjectName("primary")
            website.setIcon(fa_icon("website", "#FFFFFF"))
            website.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://vectordrive.sollium.net")))
            links.addStretch()
            links.addWidget(github)
            links.addWidget(website)
            links.addStretch()
            card_layout.addLayout(links)
            credit = QLabel("A project brought to you by the autism of RaySollium99")
            credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            credit.setStyleSheet("color: #596377; font-size: 11px; padding-top: 18px;")
            card_layout.addWidget(credit)
            wrapper = QHBoxLayout()
            wrapper.addStretch()
            wrapper.addWidget(card)
            wrapper.addStretch()
            layout.addLayout(wrapper)
            layout.addStretch(1)

        def _load_page(self, name: str) -> None:
            index = {"library": 0, "builder": 1, "settings": 2, "about": 3, "logs": 4}[name]
            self.pages.setCurrentIndex(index)
            for key, button in self.nav_buttons.items():
                button.setProperty("selected", key == name)
                button.style().unpolish(button)
                button.style().polish(button)
            self._log(f"Opened {name} page")

        def refresh_library(self) -> None:
            if not hasattr(self, "library_list"):
                return
            self.games = self.store.list_games()
            systems = sorted({game.system for game in self.games})
            selected_system = self.system_filter.currentText() if self.system_filter.count() else "All systems"
            selected_category = self.category_filter.currentText() if self.category_filter.count() else "All ROMs"
            self.system_filter.blockSignals(True)
            self.system_filter.clear()
            self.system_filter.addItem("All systems")
            self.system_filter.addItems(systems)
            self.system_filter.setCurrentText(selected_system if selected_system in systems else "All systems")
            self.system_filter.blockSignals(False)
            query = self.search.text().casefold()
            system = self.system_filter.currentText()
            category = self.category_filter.currentText()
            self.library_list.clear()
            visible = []
            for game in self.games:
                searchable = f"{game.title} {game.system} {game.rom_path} {game.metadata.get('publisher', '')}".casefold()
                if query and query not in searchable:
                    continue
                if system != "All systems" and game.system != system:
                    continue
                if category == "Main ROMs" and game.category != "main":
                    continue
                if category == "Extra ROMs" and game.category != "extra":
                    continue
                visible.append(game)
                item = QListWidgetItem(f"{game.title}  [{game.category.upper()}]")
                item.setToolTip(f"{game.system}\n{game.rom_path}")
                item.setData(Qt.ItemDataRole.UserRole, game.id)
                if game.artwork_path and game.artwork_path.is_file():
                    item.setIcon(QIcon(str(game.artwork_path)))
                else:
                    item.setIcon(fa_icon("library"))
                self.library_list.addItem(item)
            self.library_count.setText(f"{len(visible)} GAMES")
            if visible:
                self.library_list.setCurrentRow(0)
            else:
                self._show_game(None)

        def _selected_game_changed(self) -> None:
            item = self.library_list.currentItem()
            self._show_game(self.store.get(str(item.data(Qt.ItemDataRole.UserRole))) if item else None)

        def _show_game_context_menu(self, position: object) -> None:
            item = self.library_list.itemAt(position)
            if item is None:
                return
            self.library_list.setCurrentItem(item)
            menu = QMenu(self)
            choose = menu.addAction(fa_icon("scrape"), "Choose Metadata...")
            edit = menu.addAction(fa_icon("edit"), "Edit Metadata...")
            selected = menu.exec(self.library_list.viewport().mapToGlobal(position))
            if selected == choose:
                self.choose_metadata(item)
            elif selected == edit:
                self.edit_game(item)

        def _show_game(self, game: Optional[Game]) -> None:
            if game is None:
                self.detail_title.setText("Select a game")
                self.detail_subtitle.setText("Your selected game details appear here.")
                self.detail_art.setPixmap(QPixmap())
                self.detail_art.setText("NO ARTWORK")
                self.detail_meta.setText("")
                self.detail_information.clear()
                return
            self.detail_title.setText(game.title)
            self.detail_subtitle.setText(f"{game.system}  |  {game.rom_path}")
            if game.artwork_path and game.artwork_path.is_file():
                pixmap = QPixmap(str(game.artwork_path))
                self.detail_art.setText("")
                self.detail_art.setPixmap(pixmap.scaled(500, 270, Qt.AspectRatioMode.KeepAspectRatio,
                                                        Qt.TransformationMode.SmoothTransformation))
            else:
                self.detail_art.setPixmap(QPixmap())
                self.detail_art.setText("NO ARTWORK")
            metadata = game.metadata
            facts = [f"CATEGORY  {'EXTRA ROM' if game.category == 'extra' else 'MAIN ROM'}",
                    f"SYSTEM  {game.system}"]
            for key, label in (("release_year", "RELEASE YEAR"), ("genre", "GENRE"), ("players", "PLAYERS"),
                               ("region", "REGION"), ("publisher", "PUBLISHER"), ("developer", "DEVELOPER")):
                if metadata.get(key) not in (None, ""):
                    facts.append(f"{label}  {metadata[key]}")
            self.detail_meta.setText("\n".join(facts))
            self.detail_information.setPlainText(str(metadata.get("information", "")))

        def import_package(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Import VectorDrive ZIP", "", "ZIP archives (*.zip)")
            if not filename:
                return
            self._log(f"Importing package {filename}")
            try:
                info, imported = PackageReader(Path(filename)).import_into(self.store)
                self._set_status(f"Imported {len(imported)} ROMs")
                self.builder_status.setText(f"Imported {len(imported)} game(s) from {info.root}/")
                self._log(f"Imported {len(imported)} game(s) from {info.root}/")
                self.refresh_library()
            except Exception as error:
                self._log(f"Package import failed: {error}")
                QMessageBox.critical(self, "Import failed", str(error))

        def add_folder(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Add ROM Folder")
            if not folder:
                return
            category, accepted = QInputDialog.getItem(
                self, "ROM category", "Store these files as:", ("main", "extra"), 0, False,
            )
            if not accepted:
                return
            from .cli import _add_inputs
            try:
                count = _add_inputs(self.store, [Path(folder)], category)
                self._set_status(f"Library: {len(self.store.list_games())} games")
                self.builder_status.setText(f"Added {count} {category} ROM(s)")
                self._log(f"Added {count} {category} ROM(s) from {folder}")
                self.refresh_library()
            except Exception as error:
                self._log(f"ROM import failed: {error}")
                QMessageBox.critical(self, "ROM import failed", str(error))

        def choose_base(self) -> None:
            filename, _ = QFileDialog.getOpenFileName(self, "Choose VectorDrive ZIP", "", "ZIP archives (*.zip)")
            if not filename:
                return
            self._log(f"Loading base package {filename}")
            try:
                base = Path(filename).expanduser().resolve(strict=False)
                info, imported = PackageReader(base).import_into(self.store)
                self.base_zip = base
                self.base_label.setText(str(base))
                self.base_status.setText(f"{info.root}/ loaded | {info.roms} package ROMs | {len(imported)} new library entries")
                self.builder_status.setText("Base package loaded. Choose ZIP or ISO output below.")
                self._set_status(f"Base: {info.root}")
                self._log(f"Loaded {info.root}/ with {info.roms} package ROM(s); imported {len(imported)} new game(s)")
                self.refresh_library()
            except Exception as error:
                self.base_zip = None
                self._log(f"Base package failed: {error}")
                QMessageBox.critical(self, "Base ZIP failed", str(error))

        def save_settings(self) -> None:
            screen = self.settings.setdefault("screenscraper", {})
            for key in ("dev_id", "dev_password", "soft_name", "user", "password"):
                screen[key] = self.settings_fields[f"screenscraper.{key}"].text()
            self.settings["thegamesdb_api_key"] = self.settings_fields["thegamesdb_api_key"].text()
            self.settings["providers"] = [provider for provider, check in self.provider_checks.items() if check.isChecked()]
            self.settings.pop("paths", None)
            self.settings_store.save(self.settings)
            self._set_status("Settings saved")
            self._log("Saved provider settings")

        def _screen_scraper_credentials(self) -> Optional[ScreenScraperCredentials]:
            screen = self.settings.setdefault("screenscraper", {})
            if screen.get("dev_id") and screen.get("dev_password") and screen.get("soft_name"):
                return ScreenScraperCredentials(
                    str(screen["dev_id"]), str(screen["dev_password"]), str(screen["soft_name"]),
                    str(screen.get("user")) or None, str(screen.get("password")) or None,
                )
            dialog = QDialog(self)
            dialog.setWindowTitle("ScreenScraper credentials")
            form = QFormLayout(dialog)
            fields = {}
            for key, label, secret in (("dev_id", "Developer ID", False), ("dev_password", "Developer password", True),
                                       ("soft_name", "Software name", False), ("user", "User (optional)", False),
                                       ("password", "Password (optional)", True)):
                field = QLineEdit(str(screen.get(key, "VectorForge" if key == "soft_name" else "")))
                field.setEchoMode(QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)
                fields[key] = field
                form.addRow(label, field)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._log("ScreenScraper credential prompt cancelled")
                return None
            values = {key: field.text().strip() for key, field in fields.items()}
            if not values["dev_id"] or not values["dev_password"] or not values["soft_name"]:
                QMessageBox.warning(self, "Missing credentials", "Developer ID, developer password, and software name are required.")
                self._log("ScreenScraper credential prompt incomplete")
                return None
            screen.update(values)
            self.settings_store.save(self.settings)
            self._log("Saved ScreenScraper credentials")
            return ScreenScraperCredentials(
                values["dev_id"], values["dev_password"], values["soft_name"],
                values["user"] or None, values["password"] or None,
            )

        def _thegamesdb_api_key(self) -> Optional[str]:
            current = str(self.settings.get("thegamesdb_api_key", ""))
            if current:
                return current
            value, accepted = QInputDialog.getText(
                self, "TheGamesDB credentials", "API key:", QLineEdit.EchoMode.Password,
            )
            value = value.strip()
            if not accepted or not value:
                self._log("TheGamesDB API key prompt cancelled")
                return None
            self.settings["thegamesdb_api_key"] = value
            if "thegamesdb_api_key" in self.settings_fields:
                self.settings_fields["thegamesdb_api_key"].setText(value)
            self.settings_store.save(self.settings)
            self._log("Saved TheGamesDB API key")
            return value

        def choose_metadata(self, item: QListWidgetItem) -> None:
            game = self.store.get(str(item.data(Qt.ItemDataRole.UserRole)))
            if game is None:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Choose Metadata - {game.title}")
            dialog.resize(700, 480)
            layout = QVBoxLayout(dialog)
            detail = QLabel("Search ScreenScraper, TheGamesDB, or both. Select the variation to apply.")
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #8E98AC;")
            layout.addWidget(detail)
            search_row = QHBoxLayout()
            query = QLineEdit(game.title)
            query.setPlaceholderText("Game title")
            provider = QComboBox()
            provider.addItems(("All providers", "ScreenScraper", "TheGamesDB"))
            search_button = QPushButton("Search")
            search_button.setObjectName("primary")
            search_button.setIcon(fa_icon("search", "#FFFFFF"))
            search_row.addWidget(query, 1)
            search_row.addWidget(provider)
            search_row.addWidget(search_button)
            layout.addLayout(search_row)
            results = QListWidget()
            layout.addWidget(results, 1)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            )
            apply_button = buttons.button(QDialogButtonBox.StandardButton.Save)
            apply_button.setText("Apply Metadata")
            apply_button.setEnabled(False)
            layout.addWidget(buttons)
            candidates: list[ManualCandidate] = []
            credentials: Optional[ScreenScraperCredentials] = None
            api_key: Optional[str] = None

            def search_candidates() -> None:
                nonlocal credentials, api_key
                results.clear()
                candidates.clear()
                apply_button.setEnabled(False)
                names = {
                    "All providers": ("screenscraper", "thegamesdb"),
                    "ScreenScraper": ("screenscraper",),
                    "TheGamesDB": ("thegamesdb",),
                }[provider.currentText()]
                errors = []
                for name in names:
                    if name == "screenscraper":
                        credentials = self._screen_scraper_credentials()
                        if credentials is None:
                            continue
                    else:
                        api_key = self._thegamesdb_api_key()
                        if api_key is None:
                            continue
                    self._log(f"Searching {name} metadata for {game.title}")
                    try:
                        candidates.extend(find_manual_candidates(
                            game, providers=(name,), query=query.text(),
                            screenscraper=credentials, thegamesdb_api_key=api_key,
                        ))
                    except Exception as error:
                        errors.append(f"{name}: {error}")
                        self._log(f"Manual metadata search failed for {name}: {error}")
                candidates.sort(key=lambda candidate: (
                    candidate.title.casefold(), candidate.title,
                    candidate.provider, candidate.provider_id,
                ))
                for index, candidate in enumerate(candidates):
                    result_item = QListWidgetItem(candidate.label)
                    result_item.setData(Qt.ItemDataRole.UserRole, index)
                    results.addItem(result_item)
                if candidates:
                    results.setCurrentRow(0)
                    apply_button.setEnabled(True)
                    self._log(f"Found {len(candidates)} metadata candidate(s) for {game.title}")
                elif errors:
                    QMessageBox.warning(dialog, "Metadata search failed", "\n".join(errors))
                else:
                    QMessageBox.information(dialog, "No matches", "No metadata variations were found.")

            def accept_selection() -> None:
                if results.currentItem() is not None:
                    dialog.accept()

            search_button.clicked.connect(search_candidates)
            query.returnPressed.connect(search_candidates)
            results.itemDoubleClicked.connect(lambda _item: accept_selection())
            buttons.accepted.connect(accept_selection)
            buttons.rejected.connect(dialog.reject)
            if dialog.exec() != QDialog.DialogCode.Accepted or results.currentItem() is None:
                return
            selected = candidates[int(results.currentItem().data(Qt.ItemDataRole.UserRole))]
            try:
                apply_manual_candidate(
                    self.store, game, selected, temp_dir=paths.temp,
                    screenscraper=credentials, thegamesdb_api_key=api_key,
                )
                self._set_status(f"Applied metadata from {selected.provider}")
                self._log(f"Applied {selected.label} to {game.rom_path}")
                self.refresh_library()
            except Exception as error:
                self._log(f"Applying manual metadata failed: {error}")
                QMessageBox.critical(self, "Metadata update failed", str(error))

        def scrape(self) -> None:
            if self.scrape_thread is not None:
                return
            self.save_settings()
            providers = tuple(self.settings.get("providers", ["screenscraper"]))
            if not providers:
                QMessageBox.warning(self, "No providers", "Select at least one metadata provider in Settings.")
                return
            credentials = self._screen_scraper_credentials() if "screenscraper" in providers else None
            if "screenscraper" in providers and credentials is None:
                return
            store = self.store
            settings = self.settings

            class ScrapeWorker(QObject):
                finished = Signal(object)
                failed = Signal(str)
                progress = Signal(str)

                def run(worker) -> None:
                    try:
                        result = scrape_library(store, paths, providers=providers, screenscraper=credentials,
                                                thegamesdb_api_key=str(settings.get("thegamesdb_api_key", "")) or None,
                                                progress=worker.progress.emit)
                        worker.finished.emit(result)
                    except Exception as error:
                        worker.failed.emit(str(error))

            self.scrape_thread = QThread(self)
            self.scrape_worker = ScrapeWorker()
            self.scrape_worker.moveToThread(self.scrape_thread)
            self.scrape_thread.started.connect(self.scrape_worker.run)  # type: ignore[attr-defined]
            self.scrape_worker.progress.connect(self.scrape_progress)  # type: ignore[attr-defined]
            self.scrape_worker.finished.connect(self.scrape_finished)  # type: ignore[attr-defined]
            self.scrape_worker.failed.connect(self.scrape_failed)  # type: ignore[attr-defined]
            self.scrape_worker.finished.connect(self.scrape_thread.quit)  # type: ignore[attr-defined]
            self.scrape_worker.failed.connect(self.scrape_thread.quit)  # type: ignore[attr-defined]
            self.scrape_thread.finished.connect(self.scrape_thread_finished)
            self.scrape_thread.start()
            self._set_status(f"Scraping {len(store.list_games())} game(s)...")
            self._log(f"Started metadata scrape with {', '.join(providers)}")

        def scrape_finished(self, result: object) -> None:
            self.refresh_library()
            self._set_status(f"Scrape complete: {result.matched} game(s) processed")
            self._log(f"Scraping complete: {result.matched} games processed")

        def scrape_progress(self, message: str) -> None:
            self._set_status(message)
            self._log(message)

        def scrape_failed(self, message: str) -> None:
            self._set_status("Scraping failed")
            self._log(f"Scraping failed: {message}")
            QMessageBox.critical(self, "Scraping failed", message)

        def scrape_thread_finished(self) -> None:
            if self.scrape_worker is not None:
                self.scrape_worker.deleteLater()
            if self.scrape_thread is not None:
                self.scrape_thread.deleteLater()
            self.scrape_worker = None
            self.scrape_thread = None

        def edit_selected_game(self) -> None:
            item = self.library_list.currentItem()
            if item:
                self.edit_game(item)

        def edit_game(self, item: QListWidgetItem) -> None:
            game = self.store.get(str(item.data(Qt.ItemDataRole.UserRole)))
            if game is None:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Edit {game.title}")
            form = QFormLayout(dialog)
            fields = {}
            for key in ("title", "system", "genre", "region", "publisher", "developer"):
                field = QLineEdit(str(game.metadata.get(key, "")))
                fields[key] = field
                form.addRow(key.replace("_", " ").title(), field)
            information = QTextEdit(str(game.metadata.get("information", "")))
            fields["information"] = information
            form.addRow("Information", information)
            for key, maximum in (("release_year", 9999), ("players", 8), ("rating", 100)):
                spin = QSpinBox()
                spin.setRange(0, maximum)
                spin.setValue(int(game.metadata.get(key, 0) or 0))
                fields[key] = spin
                form.addRow(key.replace("_", " ").title(), spin)
            selected_artwork: list[Path] = []
            artwork_button = QPushButton("Choose Artwork")

            def choose_artwork() -> None:
                filename, _ = QFileDialog.getOpenFileName(dialog, "Choose Artwork", "", "Images (*.png *.jpg *.jpeg)")
                if filename:
                    selected_artwork[:] = [Path(filename)]
                    artwork_button.setText(Path(filename).name)

            artwork_button.clicked.connect(choose_artwork)
            form.addRow("Artwork", artwork_button)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            values = {key: field.toPlainText() if key == "information" else field.text()
                      for key, field in fields.items() if key not in {"release_year", "players", "rating"}}
            for key in ("release_year", "players", "rating"):
                values[key] = fields[key].value() or None
            try:
                self.store.update_metadata(game.id, values)
                if selected_artwork:
                    self.store.set_artwork(game.id, convert_artwork(selected_artwork[0]))
                self._log(f"Updated metadata for {game.title}")
                self.refresh_library()
            except Exception as error:
                self._log(f"Metadata update failed: {error}")
                QMessageBox.critical(self, "Metadata update failed", str(error))

        def build_package(self) -> None:
            if self.base_zip is None:
                QMessageBox.warning(self, "No base ZIP", "Choose a VectorDrive ZIP first.")
                return
            try:
                result = build_zip(self.base_zip, Path(self.zip_output.text()).expanduser(), self.store, force=True)
                self._set_status("ZIP built")
                self.builder_status.setText(f"Built {result.output} with {result.roms} ROM(s)")
                self._log(f"Built ZIP {result.output} with {result.roms} ROM(s)")
            except Exception as error:
                self._log(f"ZIP build failed: {error}")
                QMessageBox.critical(self, "ZIP build failed", str(error))

        def build_iso_package(self) -> None:
            if self.base_zip is None:
                QMessageBox.warning(self, "No base ZIP", "Choose a VectorDrive ZIP first.")
                return
            try:
                result = build_iso(self.base_zip, Path(self.iso_output.text()).expanduser(), self.store, force=True)
                self._set_status("ISO built")
                self.builder_status.setText(f"Built {result.output} with {result.zip.roms} ROM(s)")
                self._log(f"Built ISO {result.output} with {result.zip.roms} ROM(s)")
            except Exception as error:
                self._log(f"ISO build failed: {error}")
                QMessageBox.critical(self, "ISO build failed", str(error))

    window = MainWindow()
    window.show()
    return application.exec()
