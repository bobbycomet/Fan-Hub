"""
Fan Curves Tab - visual curve editor with draggable points.
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QListWidget, QListWidgetItem, QDoubleSpinBox,
    QSlider, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QSpinBox, QLineEdit, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath,
    QLinearGradient, QPolygonF
)

from core.fan_curves import FanCurve, CurvePoint, PRESET_CURVES, BlendMode

logger = logging.getLogger('fanhub.curveseditor')


class CurveEditorCanvas(QWidget):
    """
    Interactive fan curve canvas.
    - Click to add points
    - Drag points to adjust
    - Right-click to remove
    """
    points_changed = pyqtSignal(list)   # List of CurvePoint

    MARGIN = 40
    MIN_TEMP = 20.0
    MAX_TEMP = 100.0
    MIN_SPEED = 0.0
    MAX_SPEED = 100.0

    def __init__(self):
        super().__init__()
        self.setMinimumSize(500, 350)
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.points: list[CurvePoint] = []
        self._dragging: int = -1   # index of point being dragged
        self._drag_id: tuple = None  # (temp, speed) snapshot before sort
        self._hover: int = -1
        self._current_temp = 0.0
        self._current_speed = 0.0

        # Presets for reference
        self.reference_curve = None

    def _to_canvas(self, temp: float, speed: float) -> QPointF:
        # BUG FIX: guard against zero-size widget (avoids division-by-zero crash
        # when the tab is first created before it has been laid out)
        w = max(1, self.width() - 2 * self.MARGIN)
        h = max(1, self.height() - 2 * self.MARGIN)
        x = self.MARGIN + (temp - self.MIN_TEMP) / (self.MAX_TEMP - self.MIN_TEMP) * w
        y = self.height() - self.MARGIN - (speed - self.MIN_SPEED) / (self.MAX_SPEED - self.MIN_SPEED) * h
        return QPointF(x, y)

    def _from_canvas(self, x: float, y: float) -> tuple[float, float]:
        # BUG FIX: guard against zero-size widget
        w = max(1, self.width() - 2 * self.MARGIN)
        h = max(1, self.height() - 2 * self.MARGIN)
        temp = self.MIN_TEMP + (x - self.MARGIN) / w * (self.MAX_TEMP - self.MIN_TEMP)
        speed = self.MIN_SPEED + (self.height() - self.MARGIN - y) / h * (self.MAX_SPEED - self.MIN_SPEED)
        temp = max(self.MIN_TEMP, min(self.MAX_TEMP, temp))
        speed = max(self.MIN_SPEED, min(self.MAX_SPEED, speed))
        return round(temp, 1), round(speed, 1)

    def _find_nearby_point(self, x: float, y: float, radius: float = 12.0) -> int:
        for i, pt in enumerate(self.points):
            cp = self._to_canvas(pt.temp, pt.speed)
            if abs(cp.x() - x) <= radius and abs(cp.y() - y) <= radius:
                return i
        return -1

    def set_points(self, points: list):
        self.points = [CurvePoint(p.temp, p.speed) for p in points]
        self.points.sort(key=lambda p: p.temp)
        self.update()

    def set_current_temp(self, temp: float):
        self._current_temp = temp
        if self.points:
            # Interpolate directly without creating a new FanCurve object
            sorted_pts = sorted(self.points, key=lambda p: p.temp)
            if temp <= sorted_pts[0].temp:
                self._current_speed = sorted_pts[0].speed
            elif temp >= sorted_pts[-1].temp:
                self._current_speed = sorted_pts[-1].speed
            else:
                self._current_speed = sorted_pts[-1].speed
                for i in range(len(sorted_pts) - 1):
                    p1, p2 = sorted_pts[i], sorted_pts[i+1]
                    if p1.temp <= temp <= p2.temp:
                        r = (temp - p1.temp) / (p2.temp - p1.temp)
                        self._current_speed = p1.speed + r * (p2.speed - p1.speed)
                        break
        self.update()

    def paintEvent(self, event):
        # BUG FIX: skip paint if widget is too small to draw anything useful
        if self.width() < 2 * self.MARGIN + 10 or self.height() < 2 * self.MARGIN + 10:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        M = self.MARGIN

        # Background
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#0d1117"))
        bg.setColorAt(1, QColor("#0a0a1a"))
        painter.fillRect(0, 0, w, h, QBrush(bg))

        # Grid
        grid_pen = QPen(QColor("#1a2040"), 1, Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)

        # Vertical grid lines (temps)
        for temp in range(20, 101, 10):
            cp = self._to_canvas(temp, 0)
            painter.drawLine(int(cp.x()), M, int(cp.x()), h - M)

        # Horizontal grid lines (speeds)
        for speed in range(0, 101, 10):
            cp = self._to_canvas(20, speed)
            painter.drawLine(M, int(cp.y()), w - M, int(cp.y()))

        # Axis labels
        painter.setPen(QPen(QColor("#8899aa")))
        font = QFont("Monospace", 8)
        painter.setFont(font)

        for temp in range(20, 101, 10):
            cp = self._to_canvas(temp, 0)
            painter.drawText(int(cp.x()) - 12, h - M + 15, f"{temp}°")

        for speed in range(0, 101, 20):
            cp = self._to_canvas(20, speed)
            painter.drawText(2, int(cp.y()) + 4, f"{speed}%")

        # Axis titles
        painter.setPen(QPen(QColor("#aabbcc")))
        painter.drawText(w // 2 - 30, h - 5, "Temperature (°C)")

        # Danger zones
        danger_start = self._to_canvas(80, 0)
        danger_end   = self._to_canvas(100, 100)
        danger_rect  = QRectF(danger_start.x(), danger_end.y(),
                               danger_end.x() - danger_start.x(),
                               danger_start.y() - danger_end.y())
        painter.fillRect(danger_rect, QBrush(QColor(255, 50, 50, 25)))

        warn_start = self._to_canvas(70, 0)
        warn_rect  = QRectF(warn_start.x(), danger_end.y(),
                             danger_start.x() - warn_start.x(),
                             danger_start.y() - danger_end.y())
        painter.fillRect(warn_rect, QBrush(QColor(255, 150, 50, 15)))

        # Reference curve (if any)
        if self.reference_curve and len(self.reference_curve.points) >= 2:
            ref_pen = QPen(QColor("#334466"), 1, Qt.PenStyle.DashLine)
            painter.setPen(ref_pen)
            pts = sorted(self.reference_curve.points, key=lambda p: p.temp)
            prev = self._to_canvas(pts[0].temp, pts[0].speed)
            for pt in pts[1:]:
                next_p = self._to_canvas(pt.temp, pt.speed)
                painter.drawLine(prev, next_p)
                prev = next_p

        # Curve fill
        if len(self.points) >= 2:
            sorted_pts = sorted(self.points, key=lambda p: p.temp)
            path = QPainterPath()
            first = self._to_canvas(sorted_pts[0].temp, sorted_pts[0].speed)
            path.moveTo(first)
            for pt in sorted_pts[1:]:
                cp = self._to_canvas(pt.temp, pt.speed)
                path.lineTo(cp)

            # Fill under curve
            last         = self._to_canvas(sorted_pts[-1].temp, 0)
            first_bottom = self._to_canvas(sorted_pts[0].temp, 0)
            path.lineTo(last)
            path.lineTo(first_bottom)
            path.closeSubpath()

            fill_grad = QLinearGradient(0, 0, 0, h)
            fill_grad.setColorAt(0, QColor(0, 180, 255, 60))
            fill_grad.setColorAt(1, QColor(0, 100, 200, 10))
            painter.fillPath(path, QBrush(fill_grad))

            # Draw curve line
            path2 = QPainterPath()
            path2.moveTo(first)
            for pt in sorted_pts[1:]:
                path2.lineTo(self._to_canvas(pt.temp, pt.speed))
            curve_pen = QPen(QColor("#00ccff"), 2)
            painter.setPen(curve_pen)
            painter.drawPath(path2)

        # Current temp indicator
        if self._current_temp > 0:
            ind_x = self._to_canvas(self._current_temp, 0).x()
            painter.setPen(QPen(QColor("#ffaa00"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(ind_x), M, int(ind_x), h - M)

            speed_pt = self._to_canvas(self._current_temp, self._current_speed)
            painter.setBrush(QBrush(QColor("#ffaa00")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(speed_pt, 6, 6)

            painter.setPen(QPen(QColor("#ffcc88")))
            painter.setFont(QFont("Monospace", 9))
            painter.drawText(int(speed_pt.x()) + 10, int(speed_pt.y()) - 5,
                             f"{self._current_temp:.0f}°→{self._current_speed:.0f}%")

        # Control points
        for i, pt in enumerate(self.points):
            cp = self._to_canvas(pt.temp, pt.speed)
            is_hover = (i == self._hover)
            is_drag  = (i == self._dragging)

            if is_drag:
                color  = QColor("#ffff00")
                radius = 9
            elif is_hover:
                color  = QColor("#88ddff")
                radius = 8
            else:
                color  = QColor("#00ccff")
                radius = 6

            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.drawEllipse(cp, radius, radius)

            # Labels
            painter.setPen(QPen(QColor("#ccddee")))
            painter.setFont(QFont("Monospace", 8))
            painter.drawText(int(cp.x()) + 10, int(cp.y()) - 5,
                             f"{pt.temp:.0f}° / {pt.speed:.0f}%")

        painter.end()

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._find_nearby_point(x, y)
            if idx >= 0:
                self._dragging = idx
                self._drag_id = (self.points[idx].temp, self.points[idx].speed)
            else:
                # Add new point
                temp, speed = self._from_canvas(x, y)
                self.points.append(CurvePoint(temp, speed))
                self.points.sort(key=lambda p: p.temp)
                self.points_changed.emit(self.points)
                self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            idx = self._find_nearby_point(x, y)
            if idx >= 0 and len(self.points) > 2:
                self.points.pop(idx)
                self.points_changed.emit(self.points)
                self.update()

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if self._dragging >= 0 and self._drag_id is not None:
            temp, speed = self._from_canvas(x, y)
            # Update the point being dragged
            self.points[self._dragging] = CurvePoint(temp, speed)
            # Sort and recover the drag index by matching the NEW temp value,
            # not by screen proximity (avoids snapping to wrong point)
            self.points.sort(key=lambda p: p.temp)
            # Find the point whose temp matches what we just wrote
            best = 0
            best_dist = float('inf')
            for i, pt in enumerate(self.points):
                d = abs(pt.temp - temp)
                if d < best_dist:
                    best_dist = d
                    best = i
            self._dragging = best
            self._drag_id = (self.points[best].temp, self.points[best].speed)
            self.points_changed.emit(self.points)
            self.update()
        else:
            self._hover = self._find_nearby_point(x, y)
            self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = -1
        self._drag_id = None

    def leaveEvent(self, event):
        self._hover = -1
        self.update()


class FanCurvesTab(QWidget):

    def __init__(self, hw_monitor, curve_engine, state):
        super().__init__()
        self.hw = hw_monitor
        self.curves = curve_engine
        self.state  = state
        self._current_curve: FanCurve = None
        self._build_ui()
        self._load_curve_list()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 10)
        layout.setSpacing(12)

        # ── Left panel ───────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)

        # Curve list
        curve_group = QGroupBox("Curves")
        curve_group.setFixedWidth(220)
        cl = QVBoxLayout(curve_group)

        self.curve_list = QListWidget()
        self.curve_list.currentRowChanged.connect(self._on_curve_selected)
        cl.addWidget(self.curve_list)

        btn_row = QHBoxLayout()
        self.new_btn = QPushButton("+ New")
        self.new_btn.clicked.connect(self._new_curve)
        btn_row.addWidget(self.new_btn)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete_curve)
        btn_row.addWidget(self.del_btn)
        cl.addLayout(btn_row)

        left.addWidget(curve_group)

        # Curve settings
        settings_group = QGroupBox("Curve Settings")
        settings_group.setFixedWidth(220)
        sl = QVBoxLayout(settings_group)

        sl.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        sl.addWidget(self.name_edit)

        sl.addWidget(QLabel("Temperature source:"))
        self.sensor_combo = QComboBox()
        self.sensor_combo.addItem("Highest (all sensors)", '__highest__')
        self.sensor_combo.addItem("Average (all sensors)", '__average__')
        for sid, sensor in self.hw.temps.items():
            self.sensor_combo.addItem(sensor.label[:30], sid)
        sl.addWidget(self.sensor_combo)

        sl.addWidget(QLabel("Blend mode:"))
        self.blend_combo = QComboBox()
        self.blend_combo.addItem("Highest temp",   BlendMode.HIGHEST.value)
        self.blend_combo.addItem("Average of all", BlendMode.AVERAGE.value)
        self.blend_combo.setToolTip(
            "Highest: use hottest sensor.\n"
            "Average: mean of all selected sensors.\n"
            "A specific sensor above overrides this blend.")
        sl.addWidget(self.blend_combo)

        sl.addWidget(QLabel("Hysteresis (°C):"))
        self.hyst_spin = QDoubleSpinBox()
        self.hyst_spin.setRange(0.0, 10.0)
        self.hyst_spin.setSingleStep(0.5)
        self.hyst_spin.setValue(2.0)
        sl.addWidget(self.hyst_spin)

        sl.addWidget(QLabel("Min speed (%):"))
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 100)
        sl.addWidget(self.min_spin)

        self.stop_check = QCheckBox("Fan stop below (°C):")
        sl.addWidget(self.stop_check)
        self.stop_spin = QDoubleSpinBox()
        self.stop_spin.setRange(0.0, 60.0)
        self.stop_spin.setValue(35.0)
        self.stop_spin.setEnabled(False)
        self.stop_check.toggled.connect(self.stop_spin.setEnabled)
        sl.addWidget(self.stop_spin)

        save_btn = QPushButton("💾 Save Curve")
        save_btn.setObjectName("applyBtn")
        save_btn.clicked.connect(self._save_curve)
        sl.addWidget(save_btn)

        left.addWidget(settings_group)

        # Points table
        pts_group = QGroupBox("Control Points")
        pts_group.setFixedWidth(220)
        pl = QVBoxLayout(pts_group)

        self.points_table = QTableWidget(0, 2)
        self.points_table.setHorizontalHeaderLabels(["Temp °C", "Speed %"])
        self.points_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.points_table.setMaximumHeight(200)
        pl.addWidget(self.points_table)

        left.addWidget(pts_group)
        left.addStretch()

        # ── Right panel: canvas ───────────────────────
        right = QVBoxLayout()

        # Preset quick-load
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Load preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESET_CURVES.keys()))
        preset_row.addWidget(self.preset_combo)
        load_preset_btn = QPushButton("Load")
        load_preset_btn.clicked.connect(self._load_preset)
        preset_row.addWidget(load_preset_btn)
        preset_row.addStretch()

        # Current temp indicator
        self.temp_display = QLabel("Current temp: --°C")
        self.temp_display.setObjectName("tempDisplay")
        preset_row.addWidget(self.temp_display)

        right.addLayout(preset_row)

        # Instructions
        hint = QLabel("Left-click: add point  •  Drag: move point  •  Right-click: remove point")
        hint.setObjectName("hintLabel")
        right.addWidget(hint)

        # Canvas
        self.canvas = CurveEditorCanvas()
        self.canvas.points_changed.connect(self._on_canvas_points_changed)
        right.addWidget(self.canvas, 1)

        layout.addLayout(left)
        layout.addLayout(right, 1)

    def _load_curve_list(self):
        self.curve_list.clear()
        for name in PRESET_CURVES:
            item = QListWidgetItem(f"[Preset] {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setForeground(QColor("#888888"))
            self.curve_list.addItem(item)

        for name, curve in self.curves.curves.items():
            if name not in PRESET_CURVES:
                item = QListWidgetItem(f"[Custom] {name}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.curve_list.addItem(item)

    def _on_curve_selected(self, row: int):
        if row < 0:
            return
        item = self.curve_list.item(row)
        if not item:
            return
        name  = item.data(Qt.ItemDataRole.UserRole)
        curve = self.curves.curves.get(name) or PRESET_CURVES.get(name)
        if curve:
            self._current_curve = FanCurve(
                name=curve.name,
                points=[CurvePoint(p.temp, p.speed) for p in curve.points],
                sensor_id=curve.sensor_id,
                hysteresis=curve.hysteresis,
                min_speed=curve.min_speed,
                stop_below=curve.stop_below,
            )
            self.canvas.set_points(curve.points)
            self.name_edit.setText(curve.name)
            self.hyst_spin.setValue(curve.hysteresis)
            self.min_spin.setValue(int(curve.min_speed))
            if curve.stop_below is not None:
                self.stop_check.setChecked(True)
                self.stop_spin.setValue(curve.stop_below)
            else:
                self.stop_check.setChecked(False)
            if curve.sensor_id:
                # Load sensor selection — handle legacy single sensor_id
                if curve.sensor_id:
                    idx = self.sensor_combo.findData(curve.sensor_id)
                    if idx >= 0:
                        self.sensor_combo.setCurrentIndex(idx)
                elif curve.blend_mode == BlendMode.AVERAGE:
                    idx = self.sensor_combo.findData('__average__')
                    if idx >= 0:
                        self.sensor_combo.setCurrentIndex(idx)
                else:
                    self.sensor_combo.setCurrentIndex(0)  # highest
                # Load blend mode
                bm_idx = self.blend_combo.findData(curve.blend_mode.value)
                if bm_idx >= 0:
                    self.blend_combo.setCurrentIndex(bm_idx)
            self._update_points_table()

    def _on_canvas_points_changed(self, points: list):
        if self._current_curve:
            self._current_curve.points = points
        self._update_points_table()

    def _update_points_table(self):
        if not self._current_curve:
            return
        pts = sorted(self._current_curve.points, key=lambda p: p.temp)
        self.points_table.setRowCount(len(pts))
        for i, pt in enumerate(pts):
            self.points_table.setItem(i, 0, QTableWidgetItem(f"{pt.temp:.1f}"))
            self.points_table.setItem(i, 1, QTableWidgetItem(f"{pt.speed:.1f}"))

    def _new_curve(self):
        curve = FanCurve(
            name="Custom Curve",
            points=[
                CurvePoint(30, 20), CurvePoint(50, 40),
                CurvePoint(70, 70), CurvePoint(85, 100),
            ],
        )
        self._current_curve = curve
        self.canvas.set_points(curve.points)
        self.name_edit.setText("Custom Curve")

    def _save_curve(self):
        if not self._current_curve:
            return
        name = self.name_edit.text().strip() or "Custom"
        self._current_curve.name       = name
        self._current_curve.sensor_id  = self.sensor_combo.currentData()
        self._current_curve.hysteresis = self.hyst_spin.value()
        self._current_curve.min_speed  = float(self.min_spin.value())
        self._current_curve.stop_below = (
            self.stop_spin.value() if self.stop_check.isChecked() else None
        )
        self.curves.add_custom_curve(self._current_curve)
        self._load_curve_list()
        logger.info(f"Saved custom curve: {name}")

    def _delete_curve(self):
        row = self.curve_list.currentRow()
        if row < 0:
            return
        item = self.curve_list.item(row)
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name in PRESET_CURVES:
            QMessageBox.warning(self, "Cannot Delete", "Cannot delete preset curves.")
            return
        if name in self.curves.curves:
            del self.curves.curves[name]
        self._load_curve_list()

    def _load_preset(self):
        name  = self.preset_combo.currentText()
        curve = PRESET_CURVES.get(name)
        if curve:
            self._current_curve = FanCurve(
                name=curve.name,
                points=[CurvePoint(p.temp, p.speed) for p in curve.points],
                sensor_id=curve.sensor_id,
                hysteresis=curve.hysteresis,
                min_speed=curve.min_speed,
                stop_below=curve.stop_below,
            )
            self.canvas.set_points(curve.points)

    def update_temps(self, temps: dict):
        if temps:
            max_temp = max(temps.values())
            # The temps dict already contains values in the user's chosen unit
            # (converted by PollingWorker), so display whatever unit was emitted
            unit = self.state.settings.get('temp_unit', 'C')
            unit_sym = '°F' if unit == 'F' else '°C'
            self.temp_display.setText(f"Current temp: {max_temp:.1f}{unit_sym}")
            # Canvas curves are always in °C; convert back if needed
            if unit == 'F':
                temp_c = (max_temp - 32) * 5 / 9
            else:
                temp_c = max_temp
            self.canvas.set_current_temp(temp_c)

    def refresh(self):
        self._load_curve_list()
        self.sensor_combo.clear()
        self.sensor_combo.addItem("(highest)", None)
        for sid, sensor in self.hw.temps.items():
            self.sensor_combo.addItem(sensor.label[:30], sid)
