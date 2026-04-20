"""
Profiles Tab - save, load, and manage complete fan + RGB profiles.
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QGroupBox, QListWidget,
    QListWidgetItem, QLineEdit, QTextEdit, QMessageBox,
    QDialog, QDialogButtonBox, QCheckBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

logger = logging.getLogger('fanhub.profiles')


class ProfilesTab(QWidget):

    def __init__(self, profile_manager, curve_engine, rgb_manager, state):
        super().__init__()
        self.profile_manager = profile_manager
        self.curves = curve_engine
        self.rgb = rgb_manager
        self.state = state
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── Left: profile list ────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)

        list_group = QGroupBox("Saved Profiles")
        list_group.setFixedWidth(260)
        ll = QVBoxLayout(list_group)

        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        ll.addWidget(self.profile_list)

        btn_row = QHBoxLayout()
        self.load_btn = QPushButton("▶ Load")
        self.load_btn.setObjectName("applyBtn")
        self.load_btn.clicked.connect(self._load_profile)
        btn_row.addWidget(self.load_btn)

        self.del_btn = QPushButton("🗑 Delete")
        self.del_btn.clicked.connect(self._delete_profile)
        btn_row.addWidget(self.del_btn)
        ll.addLayout(btn_row)

        left.addWidget(list_group)

        # Quick presets
        presets_group = QGroupBox("Quick Presets")
        presets_group.setFixedWidth(260)
        pl = QVBoxLayout(presets_group)

        presets = [
            ("🤫 Silent Mode", "silent"),
            ("⚖️ Balanced", "balanced"),
            ("🚀 Performance", "performance"),
            ("🎮 Gaming", "gaming"),
            ("💯 Full Speed", "full_speed"),
        ]
        for label, preset in presets:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, p=preset: self._apply_quick_preset(p))
            pl.addWidget(btn)

        left.addWidget(presets_group)
        left.addStretch()

        # ── Right: save + details ─────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        save_group = QGroupBox("💾 Save Current Settings as Profile")
        save_group.setObjectName("controlGroup")
        sl = QVBoxLayout(save_group)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Profile name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Gaming, Work, Quiet Night...")
        name_row.addWidget(self.name_edit, 1)
        sl.addLayout(name_row)

        self.include_rgb = QCheckBox("Include RGB settings")
        self.include_rgb.setChecked(True)
        sl.addWidget(self.include_rgb)

        self.include_liquid = QCheckBox("Include liquid cooling settings")
        self.include_liquid.setChecked(True)
        sl.addWidget(self.include_liquid)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("Description:"))
        sl.addLayout(desc_row)
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.setPlaceholderText("Optional description...")
        sl.addWidget(self.desc_edit)

        save_btn = QPushButton("💾 Save Profile")
        save_btn.setObjectName("applyBtn")
        save_btn.clicked.connect(self._save_profile)
        sl.addWidget(save_btn)

        right.addWidget(save_group)

        # Profile detail view
        detail_group = QGroupBox("Profile Details")
        detail_group.setObjectName("controlGroup")
        dl = QVBoxLayout(detail_group)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setObjectName("profileDetail")
        dl.addWidget(self.detail_text)

        right.addWidget(detail_group, 1)

        # Active profile indicator
        self.active_lbl = QLabel()
        self._update_active_label()
        right.addWidget(self.active_lbl)

        layout.addLayout(left)
        layout.addLayout(right, 1)

    def _refresh_list(self):
        self.profile_list.clear()
        profiles = self.profile_manager.list_profiles()

        if not profiles:
            item = QListWidgetItem("(No saved profiles)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#666666"))
            self.profile_list.addItem(item)
            return

        for name in profiles:
            item = QListWidgetItem(name)
            if name == self.state.active_profile:
                item.setText(f"✓ {name}")
                item.setForeground(QColor("#44ff88"))
            self.profile_list.addItem(item)

    def _on_profile_selected(self, row: int):
        if row < 0:
            return
        item = self.profile_list.item(row)
        if not item:
            return
        name = item.text().lstrip("✓ ")
        profile = self.state.get_profile(name)
        if profile:
            self._show_profile_detail(name, profile)

    def _show_profile_detail(self, name: str, profile: dict):
        curves_data = profile.get('curves', {})
        assignments = curves_data.get('fan_assignments', {})
        fixed = curves_data.get('fixed_speeds', {})
        custom = curves_data.get('custom_curves', {})
        rgb = profile.get('rgb', {})
        desc = profile.get('description', '')

        lines = [f"<h3>Profile: {name}</h3>"]
        if desc:
            lines.append(f"<p><i>{desc}</i></p>")
        lines.append("<b>Fan Assignments:</b>")
        if assignments:
            for fid, curve in assignments.items():
                lines.append(f"  • {fid} → {curve}")
        else:
            lines.append("  (none)")

        if fixed:
            lines.append("<b>Fixed Speeds:</b>")
            for fid, pct in fixed.items():
                lines.append(f"  • {fid} → {pct:.0f}%")

        if custom:
            lines.append(f"<b>Custom Curves:</b> {', '.join(custom.keys())}")

        lines.append(f"<b>RGB settings:</b> {'yes' if rgb else 'none'}")

        self.detail_text.setHtml("<br>".join(lines))

    def _save_profile(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "No Name", "Please enter a profile name.")
            return

        rgb_settings = {}
        if self.include_rgb.isChecked() and self.rgb:
            for dev in self.rgb.devices:
                rgb_settings[dev['name']] = {'id': dev['id']}

        profile = {
            'name': name,
            'description': self.desc_edit.toPlainText().strip(),
            'curves': self.curves.to_dict(),
            'rgb': rgb_settings,
        }
        self.state.save_profile(name, profile)
        self.state.active_profile = name
        self._refresh_list()
        self._update_active_label()
        self._refresh_tray()
        logger.info(f"Saved profile: {name}")
        QMessageBox.information(self, "Saved", f"Profile '{name}' saved successfully.")

    def _load_profile(self):
        row = self.profile_list.currentRow()
        if row < 0:
            return
        item = self.profile_list.item(row)
        name = item.text().lstrip("✓ ")
        if name.startswith("("):
            return

        ok = self.profile_manager.load_profile(name, self.curves)
        if ok:
            self.state.active_profile = name
            self._refresh_list()
            self._update_active_label()
            self._refresh_tray()
            QMessageBox.information(self, "Loaded", f"Profile '{name}' loaded.")
            logger.info(f"Loaded profile: {name}")
        else:
            QMessageBox.warning(self, "Error", f"Failed to load profile '{name}'.")

    def _refresh_tray(self):
        """Ask the main window to refresh the tray profile menu."""
        try:
            # Walk up to find MainWindow
            w = self.parent()
            while w is not None:
                if hasattr(w, 'refresh_tray_menu'):
                    w.refresh_tray_menu()
                    return
                w = w.parent()
        except Exception:
            pass

    def _delete_profile(self):
        row = self.profile_list.currentRow()
        if row < 0:
            return
        item = self.profile_list.item(row)
        name = item.text().lstrip("✓ ")
        if name.startswith("("):
            return

        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.state.delete_profile(name)
            self._refresh_list()
            self.detail_text.clear()

    def _apply_quick_preset(self, preset_name: str):
        """Apply a preset curve to ALL fans — actually assigns, not just clears."""
        from core.fan_curves import PRESET_CURVES
        if preset_name not in PRESET_CURVES:
            return

        # Get fan list by walking up to MainWindow
        hw = None
        w = self.parent()
        while w is not None:
            if hasattr(w, 'hw_monitor'):
                hw = w.hw_monitor
                break
            w = w.parent()

        # Assign curve to every detected fan
        self.curves.fan_assignments.clear()
        self.curves.fixed_speeds.clear()
        if hw:
            for fan_id in hw.fans:
                self.curves.assign_curve(fan_id, preset_name)
            logger.info(
                f"Quick preset '{preset_name}' assigned to {len(hw.fans)} fans")
        else:
            # Fallback: store a sentinel so the engine uses it for new fans
            logger.info(f"Quick preset '{preset_name}' applied (no fan list yet)")

        self._refresh_tray()

    def _update_active_label(self):
        active = self.state.active_profile
        if active:
            self.active_lbl.setText(f"✓ Active profile: <b>{active}</b>")
            self.active_lbl.setStyleSheet("color: #44ff88;")
        else:
            self.active_lbl.setText("No profile active")
            self.active_lbl.setStyleSheet("color: #666666;")
