"""
Dashboard Tab - live overview of all temps, fan RPMs, and system health.
Uses a wrapping FlowLayout so gauges never get clipped regardless of count.
"""
import logging
from collections import deque
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QScrollArea, QGroupBox, QProgressBar,
    QSizePolicy, QLayout
)
from PyQt6.QtCore import Qt, QRect, QSize, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath

try:
    from PyQt6.QtCharts import QChart, QChartView, QSplineSeries, QValueAxis
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False

logger = logging.getLogger('fanhub.dashboard')

HISTORY_LEN = 120   # 2 minutes at 1 s interval


# ── Flow Layout ───────────────────────────────────────────────────────────────

class FlowLayout(QLayout):
    """Wrapping flow layout — items wrap to next row when they run out of space."""

    def __init__(self, parent=None, h_spacing=8, v_spacing=8):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        return self._h_spacing

    def verticalSpacing(self):
        return self._v_spacing

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            # Unparent the widget so it doesn't remain as an invisible
            # child of the container after removal
            if item.widget() is not None:
                item.widget().setParent(None)
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            wid = item.widget()
            space_x = self._h_spacing
            space_y = self._v_spacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and row_height > 0:
                x = effective.x()
                y += row_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            row_height = max(row_height, item.sizeHint().height())

        return y + row_height - rect.y() + margins.bottom()


# ── Gauge widgets ─────────────────────────────────────────────────────────────

class TempGauge(QFrame):
    """Compact temperature gauge card."""

    def __init__(self, label: str, warning: float = 80.0, critical: float = 90.0):
        super().__init__()
        self.label_text = label
        self.value = 0.0
        self.warning = warning
        self.critical = critical
        self.setFixedSize(148, 96)
        self.setObjectName("tempGauge")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self.name_lbl = QLabel(self._short(label))
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_lbl.setObjectName("gaugeLabel")
        self.name_lbl.setToolTip(label)
        self.name_lbl.setWordWrap(False)
        layout.addWidget(self.name_lbl)

        self.val_lbl = QLabel("--.-°C")
        self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.val_lbl.setObjectName("gaugeValue")
        layout.addWidget(self.val_lbl)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)

    def _short(self, label: str) -> str:
        # e.g. "nct6798: SYSTIN" -> "SYSTIN", keep ≤20 chars
        if ':' in label:
            label = label.split(':', 1)[1].strip()
        return label[:20]

    def update_value(self, val: float, unit_sym: str = '°C'):
        self.value = val
        self.val_lbl.setText(f"{val:.1f}{unit_sym}")
        # Keep bar scaling in a sensible range regardless of unit
        if unit_sym == '°F':
            pct = int(min(100, max(0, (val - 68) / 144 * 100)))  # 68°F–212°F range
        else:
            pct = int(min(100, max(0, (val - 20) / 80 * 100)))   # 20°C–100°C range
        self.bar.setValue(pct)

        if val >= self.critical:
            color = "#ff2020"
        elif val >= self.warning:
            color = "#ff8800"
        else:
            color = "#00ccff"

        self.val_lbl.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: bold;")
        self.bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
            f"QProgressBar {{ background: #1a1a2e; border-radius: 3px; border: none; }}"
        )


class FanCard(QFrame):
    """Fan status card."""

    def __init__(self, fan_id: str, label: str):
        super().__init__()
        self.fan_id = fan_id
        self.setFixedSize(162, 110)
        self.setObjectName("fanCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        short = label[:22] if len(label) <= 22 else label[:19] + '…'
        self.name_lbl = QLabel(short)
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_lbl.setObjectName("fanCardLabel")
        self.name_lbl.setToolTip(label)
        layout.addWidget(self.name_lbl)

        self.rpm_lbl = QLabel("-- RPM")
        self.rpm_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rpm_lbl.setObjectName("fanRPM")
        layout.addWidget(self.rpm_lbl)

        self.pct_lbl = QLabel("--%")
        self.pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pct_lbl.setObjectName("fanPct")
        layout.addWidget(self.pct_lbl)

        self.mode_lbl = QLabel("auto")
        self.mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_lbl.setObjectName("fanMode")
        layout.addWidget(self.mode_lbl)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        layout.addWidget(self.bar)

    def update_data(self, data: dict):
        rpm  = data.get('rpm', 0)
        pct  = data.get('percent', 0.0)
        mode = data.get('mode', 'unknown')
        hub  = data.get('is_hub', False)

        self.rpm_lbl.setText(f"{rpm:,} RPM")
        self.pct_lbl.setText(f"{pct:.0f}%")
        self.mode_lbl.setText(f"{mode}" + (" [HUB]" if hub else ""))
        self.bar.setValue(int(pct))

        color = "#44ff88" if rpm > 100 else ("#ffaa00" if rpm > 0 else "#666666")
        self.rpm_lbl.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold;")


# ── Chart ─────────────────────────────────────────────────────────────────────

class TempHistoryChart(QWidget):
    """Scrolling temperature history chart (QtCharts if available)."""

    def __init__(self, max_series: int = 10):
        super().__init__()
        self.max_series = max_series
        self.history: dict = {}
        self.series_map: dict = {}
        self.tick = 0
        self._colors = [
            "#00ccff", "#ff6600", "#44ff88", "#ff2288",
            "#ffcc00", "#aa44ff", "#00ffcc", "#ff4444",
            "#88ff00", "#ff88cc",
        ]
        self.setObjectName("chartView")
        self.setMinimumHeight(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if CHARTS_AVAILABLE:
            self._init_charts(layout)
        else:
            self._chart_widget = None
            lbl = QLabel("Install PyQt6-Charts for the temperature graph:\n"
                         "  pip install PyQt6-Charts")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #446688; font-size: 11px;")
            layout.addWidget(lbl)

    def _init_charts(self, layout):
        self.chart_obj = QChart()
        self._chart_view = QChartView(self.chart_obj)
        self.chart_obj.setTitle("Temperature History (°C)")
        self.chart_obj.setBackgroundBrush(QBrush(QColor("#08080f")))
        self.chart_obj.setTitleBrush(QBrush(QColor("#aabbcc")))
        self.chart_obj.legend().setVisible(True)
        self.chart_obj.legend().setLabelColor(QColor("#8899aa"))
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._chart_view.setBackgroundBrush(QBrush(QColor("#08080f")))

        self.x_axis = QValueAxis()
        self.x_axis.setRange(0, HISTORY_LEN)
        self.x_axis.setTitleText("Seconds ago")
        self.x_axis.setLabelsBrush(QBrush(QColor("#778899")))
        self.x_axis.setGridLineColor(QColor("#1a1a33"))
        self.x_axis.setTitleBrush(QBrush(QColor("#556677")))

        self.y_axis = QValueAxis()
        self.y_axis.setRange(20, 100)
        self.y_axis.setTitleText("°C")
        self.y_axis.setLabelsBrush(QBrush(QColor("#778899")))
        self.y_axis.setGridLineColor(QColor("#1a1a33"))
        self.y_axis.setTitleBrush(QBrush(QColor("#556677")))

        self.chart_obj.addAxis(self.x_axis, Qt.AlignmentFlag.AlignBottom)
        self.chart_obj.addAxis(self.y_axis, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._chart_view)

    def update_temps(self, temps: dict):
        self.tick += 1

        for sid, value in temps.items():
            if sid not in self.history:
                if len(self.history) >= self.max_series:
                    continue
                self.history[sid] = deque(maxlen=HISTORY_LEN)

                if CHARTS_AVAILABLE:
                    series = QSplineSeries()
                    color = QColor(self._colors[len(self.series_map) % len(self._colors)])
                    pen = QPen(color)
                    pen.setWidth(2)
                    series.setPen(pen)
                    label = sid.split('_temp')[0].replace('hwmon', 'hw')
                    series.setName(label[:20])
                    self.chart_obj.addSeries(series)
                    series.attachAxis(self.x_axis)
                    series.attachAxis(self.y_axis)
                    self.series_map[sid] = series

            self.history[sid].append(value)

        if not CHARTS_AVAILABLE:
            return

        for sid, series in self.series_map.items():
            series.clear()
            hist  = list(self.history.get(sid, []))
            start = max(0, self.tick - HISTORY_LEN)
            for i, val in enumerate(hist):
                series.append(start + i, val)

        all_vals = [v for h in self.history.values() for v in h]
        if all_vals:
            self.y_axis.setRange(max(0, min(all_vals) - 5),
                                  min(110, max(all_vals) + 10))

        if self.tick > HISTORY_LEN:
            self.x_axis.setRange(self.tick - HISTORY_LEN, self.tick)
        else:
            self.x_axis.setRange(0, HISTORY_LEN)


# ── Main Dashboard Tab ────────────────────────────────────────────────────────

class DashboardTab(QWidget):

    def __init__(self, hw_monitor, state):
        super().__init__()
        self.hw    = hw_monitor
        self.state = state
        self._temp_gauges: dict = {}
        self._fan_cards:   dict = {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        # ── Top section: temps + fans side by side ────
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Temp group — scrollable, wrapping
        temp_group = QGroupBox("Temperatures")
        temp_group.setObjectName("dashGroup")
        temp_inner = QVBoxLayout(temp_group)
        temp_inner.setContentsMargins(6, 4, 6, 6)

        self.temp_scroll = QScrollArea()
        self.temp_scroll.setWidgetResizable(True)
        self.temp_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.temp_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.temp_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.temp_scroll.setMinimumHeight(180)

        self.temp_container = QWidget()
        self.temp_flow = FlowLayout(self.temp_container, h_spacing=8, v_spacing=8)
        self.temp_container.setLayout(self.temp_flow)
        self.temp_scroll.setWidget(self.temp_container)
        temp_inner.addWidget(self.temp_scroll)
        top_row.addWidget(temp_group, 3)

        # Fan group — scrollable, wrapping
        fan_group = QGroupBox("Fans")
        fan_group.setObjectName("dashGroup")
        fan_inner = QVBoxLayout(fan_group)
        fan_inner.setContentsMargins(6, 4, 6, 6)

        self.fan_scroll = QScrollArea()
        self.fan_scroll.setWidgetResizable(True)
        self.fan_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fan_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.fan_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.fan_scroll.setMinimumHeight(180)

        self.fan_container = QWidget()
        self.fan_flow = FlowLayout(self.fan_container, h_spacing=8, v_spacing=8)
        self.fan_container.setLayout(self.fan_flow)
        self.fan_scroll.setWidget(self.fan_container)
        fan_inner.addWidget(self.fan_scroll)
        top_row.addWidget(fan_group, 3)

        outer.addLayout(top_row)

        # ── Chart ─────────────────────────────────────
        self.chart = TempHistoryChart()
        outer.addWidget(self.chart, 1)

        # ── Liquid summary ─────────────────────────────
        self.liquid_group = QGroupBox("Liquid Cooling")
        self.liquid_group.setObjectName("dashGroup")
        self.liquid_layout = QHBoxLayout(self.liquid_group)
        self.liquid_layout.setContentsMargins(8, 4, 8, 8)
        outer.addWidget(self.liquid_group)

        # Populate initial widgets
        self._init_temp_gauges()
        self._init_fan_cards()

    # ── Population ─────────────────────────────────────

    def _init_temp_gauges(self):
        for sid, sensor in self.hw.temps.items():
            self._add_temp_gauge(sid, sensor.label,
                                 sensor.critical or 95.0,
                                 sensor.high or 80.0)

    def _add_temp_gauge(self, sid: str, label: str,
                        critical: float = 95.0, high: float = 80.0):
        if sid not in self._temp_gauges:
            gauge = TempGauge(label, warning=high, critical=critical)
            self._temp_gauges[sid] = gauge
            self.temp_flow.addWidget(gauge)
            self.temp_container.adjustSize()

    def _init_fan_cards(self):
        for fid, fan in self.hw.fans.items():
            if fid not in self._fan_cards:
                card = FanCard(fid, fan.label)
                self._fan_cards[fid] = card
                self.fan_flow.addWidget(card)
                self.fan_container.adjustSize()

    # ── Live updates ────────────────────────────────────

    def update_temps(self, temps: dict):
        unit     = self.state.settings.get('temp_unit', 'C')
        unit_sym = '°F' if unit == 'F' else '°C'

        for sid, val in temps.items():
            if sid not in self._temp_gauges:
                sensor = self.hw.temps.get(sid)
                label  = sensor.label if sensor else sid
                crit   = (sensor.critical or 95.0) if sensor else 95.0
                high   = (sensor.high    or 80.0)  if sensor else 80.0
                # Adjust thresholds for Fahrenheit
                if unit == 'F':
                    crit = crit * 9/5 + 32
                    high = high * 9/5 + 32
                self._add_temp_gauge(sid, label, crit, high)

            self._temp_gauges[sid].update_value(val, unit_sym)

        self.chart.update_temps(temps)

    def update_fans(self, fans: dict):
        for fid, data in fans.items():
            if fid not in self._fan_cards:
                label = data.get('label', fid)
                card  = FanCard(fid, label)
                self._fan_cards[fid] = card
                self.fan_flow.addWidget(card)
                self.fan_container.adjustSize()

            self._fan_cards[fid].update_data(data)

    def update_liquid(self, devices: list):
        # Clear and rebuild
        while self.liquid_layout.count():
            item = self.liquid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not devices:
            lbl = QLabel("No liquid cooling devices detected")
            lbl.setStyleSheet("color: #445566;")
            self.liquid_layout.addWidget(lbl)
            self.liquid_layout.addStretch()
            return

        for dev in devices:
            frame = QFrame()
            frame.setObjectName("liquidCard")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(10, 8, 10, 8)
            fl.setSpacing(3)
            fl.addWidget(QLabel(f"<b>{dev.name}</b>"))
            for t in dev.temps:
                fl.addWidget(QLabel(f"  Coolant: {t['value']:.1f}°C"))
            for f in dev.fans:
                fl.addWidget(QLabel(f"  Fan: {f.get('rpm', '--')} RPM"))
            if dev.pump:
                rpm  = dev.pump.get('rpm', '--')
                duty = dev.pump.get('duty', '')
                fl.addWidget(QLabel(f"  Pump: {rpm} RPM" +
                                    (f" ({duty}%)" if duty else "")))
            self.liquid_layout.addWidget(frame)

        self.liquid_layout.addStretch()
