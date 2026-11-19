"""外观与行为设置弹窗：支持低调纯色 / 自定义涨跌色、字体、透明度、任务栏定位与数据源切换。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stock_window.models.settings import (
    AppConfig,
    AppearanceConfig,
    ColorMode,
    PollingConfig,
    WindowAnchor,
    WindowConfig,
    WindowMode,
)
from stock_window.models.stock import StockItem, StockQuote
from stock_window.services.formatter import DisplayFormatter


class _ColorPickerButton(QPushButton):
    """带色块与十六进制色号展示的颜色选择按钮。"""

    color_changed = Signal(str)

    def __init__(self, initial_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = initial_color
        self.setMinimumWidth(115)
        self.clicked.connect(self._pick_color)
        self._update_style()

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self._update_style()
        self.color_changed.emit(self._color)

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "选择文字或背景颜色")
        if chosen.isValid():
            self.set_color(chosen.name().upper())

    def _update_style(self) -> None:
        c = QColor(self._color)
        # 根据背景亮度自动反选按钮文字颜色，保证色号清晰可读
        luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        fg = "#111111" if luminance > 140 else "#F4F4F4"
        self.setText(self._color.upper())
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; color: {fg}; "
            "border: 1px solid #888888; border-radius: 3px; padding: 3px 8px; }}"
        )


class SettingsDialog(QDialog):
    """外观、任务栏定位与数据源设置对话框（支持实时预览与一键应用）。"""

    # 点击「应用」时触发，允许用户不关闭设置框直接在任务栏看到效果
    config_applied = Signal(object)

    def __init__(
        self,
        config: AppConfig,
        quote_providers: list[str],
        search_providers: list[str],
        formatter: DisplayFormatter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("外观与行为设置 - StockWindow")
        self.resize(540, 560)

        self._source_config = AppConfig.from_dict(config.to_dict())
        self._quote_providers = quote_providers or ["tencent"]
        self._search_providers = search_providers or ["tencent"]
        self._formatter = formatter

        self._build_ui()
        self._load_values(self._source_config)
        self._refresh_preview()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_appearance_tab(), "外观与配色")
        tabs.addTab(self._build_window_tab(), "任务栏与行为")
        tabs.addTab(self._build_polling_tab(), "行情与数据源")
        root.addWidget(tabs, 1)

        # ---- 底部实时预览条（模拟深色任务栏效果） ----
        preview_group = QGroupBox("任务栏实时预览", self)
        preview_layout = QHBoxLayout(preview_group)
        self._preview_container = QWidget(preview_group)
        self._preview_container.setMinimumHeight(40)
        container_layout = QHBoxLayout(self._preview_container)
        container_layout.setContentsMargins(12, 6, 12, 6)
        self._preview_label_up = QLabel(self._preview_container)
        self._preview_label_down = QLabel(self._preview_container)
        container_layout.addWidget(self._preview_label_up)
        container_layout.addSpacing(14)
        container_layout.addWidget(self._preview_label_down)
        container_layout.addStretch(1)
        preview_layout.addWidget(self._preview_container)
        root.addWidget(preview_group)

        # ---- 底部按钮 ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        root.addWidget(buttons)

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)

        # 配色模式分组
        color_group = QGroupBox("配色模式（解决红绿太显眼）", page)
        color_layout = QVBoxLayout(color_group)

        mode_row = QHBoxLayout()
        self._radio_mono = QRadioButton("低调纯色模式（推荐，涨跌统一颜色）", color_group)
        self._radio_trend = QRadioButton("自定义涨跌色模式", color_group)
        self._radio_mono.toggled.connect(self._on_color_mode_changed)
        mode_row.addWidget(self._radio_mono)
        mode_row.addWidget(self._radio_trend)
        color_layout.addLayout(mode_row)

        # 快捷低饱和色预设
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("纯色快捷预设：", color_group))
        for label, hex_val in [
            ("柔和浅灰", "#D8DCE2"),
            ("极低调暗灰", "#9CA3AF"),
            ("纯白", "#F5F5F5"),
            ("浅色任务栏黑字", "#2B2B2B"),
        ]:
            btn = QPushButton(label, color_group)
            btn.clicked.connect(lambda _checked=False, c=hex_val: self._apply_mono_preset(c))
            preset_row.addWidget(btn)
        color_layout.addLayout(preset_row)

        color_form = QFormLayout()
        self._btn_mono_color = _ColorPickerButton("#D8DCE2", color_group)
        self._btn_mono_color.color_changed.connect(self._refresh_preview)
        color_form.addRow("纯色文字颜色：", self._btn_mono_color)

        trend_row = QHBoxLayout()
        self._btn_up_color = _ColorPickerButton("#D98A8A", color_group)
        self._btn_down_color = _ColorPickerButton("#7DB89B", color_group)
        self._btn_flat_color = _ColorPickerButton("#B8BFC8", color_group)
        for btn in (self._btn_up_color, self._btn_down_color, self._btn_flat_color):
            btn.color_changed.connect(self._refresh_preview)
        trend_row.addWidget(QLabel("涨:", color_group))
        trend_row.addWidget(self._btn_up_color)
        trend_row.addWidget(QLabel("跌:", color_group))
        trend_row.addWidget(self._btn_down_color)
        trend_row.addWidget(QLabel("平:", color_group))
        trend_row.addWidget(self._btn_flat_color)
        color_form.addRow("涨跌自定义色：", trend_row)

        bg_row = QHBoxLayout()
        self._btn_bg_color = _ColorPickerButton("#1F1F1F", color_group)
        self._btn_bg_color.color_changed.connect(self._refresh_preview)
        self._slider_bg_alpha = QSlider(Qt.Orientation.Horizontal, color_group)
        self._slider_bg_alpha.setRange(0, 255)
        self._slider_bg_alpha.valueChanged.connect(self._refresh_preview)
        self._lbl_bg_alpha = QLabel("0", color_group)
        self._lbl_bg_alpha.setMinimumWidth(30)
        bg_row.addWidget(self._btn_bg_color)
        bg_row.addWidget(QLabel("背景透明度:", color_group))
        bg_row.addWidget(self._slider_bg_alpha, 1)
        bg_row.addWidget(self._lbl_bg_alpha)
        color_form.addRow("背景色与透明：", bg_row)

        color_layout.addLayout(color_form)
        layout.addWidget(color_group)

        # 字体与展示字段分组
        font_group = QGroupBox("字体与显示字段", page)
        font_form = QFormLayout(font_group)

        font_row = QHBoxLayout()
        self._font_combo = QFontComboBox(font_group)
        self._font_combo.currentFontChanged.connect(self._refresh_preview)
        self._spin_font_size = QSpinBox(font_group)
        self._spin_font_size.setRange(7, 24)
        self._spin_font_size.valueChanged.connect(self._refresh_preview)
        self._chk_font_bold = QCheckBox("加粗", font_group)
        self._chk_font_bold.toggled.connect(self._refresh_preview)
        font_row.addWidget(self._font_combo, 1)
        font_row.addWidget(QLabel("字号:", font_group))
        font_row.addWidget(self._spin_font_size)
        font_row.addWidget(self._chk_font_bold)
        font_form.addRow("字体设置：", font_row)

        self._spin_spacing = QSpinBox(font_group)
        self._spin_spacing.setRange(4, 48)
        self._spin_spacing.setSuffix(" px")
        self._spin_spacing.valueChanged.connect(self._refresh_preview)
        font_form.addRow("条目间距：", self._spin_spacing)

        field_row1 = QHBoxLayout()
        self._chk_show_name = QCheckBox("显示名称/简称", font_group)
        self._chk_show_price = QCheckBox("显示现价", font_group)
        self._chk_show_pct = QCheckBox("显示涨跌幅(%)", font_group)
        field_row1.addWidget(self._chk_show_name)
        field_row1.addWidget(self._chk_show_price)
        field_row1.addWidget(self._chk_show_pct)
        font_form.addRow("显示内容：", field_row1)

        field_row2 = QHBoxLayout()
        self._chk_show_amt = QCheckBox("显示涨跌额", font_group)
        self._chk_show_sign = QCheckBox("显示 +/- 号", font_group)
        self._chk_auto_prec = QCheckBox("ETF/低价自动3位小数", font_group)
        field_row2.addWidget(self._chk_show_amt)
        field_row2.addWidget(self._chk_show_sign)
        field_row2.addWidget(self._chk_auto_prec)
        font_form.addRow("格式选项：", field_row2)

        for chk in (
            self._chk_show_name,
            self._chk_show_price,
            self._chk_show_pct,
            self._chk_show_amt,
            self._chk_show_sign,
            self._chk_auto_prec,
        ):
            chk.toggled.connect(self._refresh_preview)

        layout.addWidget(font_group)
        layout.addStretch(1)
        return page

    def _build_window_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self._combo_mode = QComboBox(page)
        self._combo_mode.addItem("贴靠 Windows 任务栏（推荐）", WindowMode.DOCK_TASKBAR.value)
        self._combo_mode.addItem("自由悬浮窗口", WindowMode.FREE_FLOAT.value)
        form.addRow("定位模式：", self._combo_mode)

        self._combo_anchor = QComboBox(page)
        self._combo_anchor.addItem("任务栏左下角", WindowAnchor.BOTTOM_LEFT.value)
        self._combo_anchor.addItem("任务栏右下角（托盘左侧）", WindowAnchor.BOTTOM_RIGHT.value)
        form.addRow("任务栏停靠边：", self._combo_anchor)

        offset_row = QHBoxLayout()
        self._spin_offset_x = QSpinBox(page)
        self._spin_offset_x.setRange(-2000, 4000)
        self._spin_offset_x.setSuffix(" px")
        self._spin_offset_y = QSpinBox(page)
        self._spin_offset_y.setRange(-200, 200)
        self._spin_offset_y.setSuffix(" px")
        offset_row.addWidget(QLabel("水平 X:", page))
        offset_row.addWidget(self._spin_offset_x)
        offset_row.addWidget(QLabel("垂直 Y:", page))
        offset_row.addWidget(self._spin_offset_y)
        form.addRow("贴靠偏移微调：", offset_row)

        self._chk_locked = QCheckBox("锁定位置（取消勾选后可直接鼠标拖动股票条定位）", page)
        form.addRow("位置保护：", self._chk_locked)

        self._spin_max_visible = QSpinBox(page)
        self._spin_max_visible.setRange(1, 10)
        self._spin_max_visible.setSuffix(" 条")
        form.addRow("同时显示条数：", self._spin_max_visible)

        self._spin_rotate = QSpinBox(page)
        self._spin_rotate.setRange(0, 300)
        self._spin_rotate.setSuffix(" 秒（0 = 仅鼠标滚轮切换）")
        form.addRow("多条自动轮播：", self._spin_rotate)

        self._chk_fullscreen_hide = QCheckBox("检测到全屏视频/游戏/PPT 时自动隐藏", page)
        form.addRow("全屏避让：", self._chk_fullscreen_hide)

        boss_row = QHBoxLayout()
        self._chk_boss_enabled = QCheckBox("启用全局老板键", page)
        self._edit_boss_key = QLineEdit(page)
        self._edit_boss_key.setPlaceholderText("如 Ctrl+Alt+H")
        boss_row.addWidget(self._chk_boss_enabled)
        boss_row.addWidget(self._edit_boss_key, 1)
        form.addRow("一键隐藏热键：", boss_row)

        return page

    def _build_polling_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)

        self._combo_quote_provider = QComboBox(page)
        for name in self._quote_providers:
            self._combo_quote_provider.addItem(name, name)
        form.addRow("行情数据源：", self._combo_quote_provider)

        self._combo_search_provider = QComboBox(page)
        for name in self._search_providers:
            self._combo_search_provider.addItem(name, name)
        form.addRow("搜索数据源：", self._combo_search_provider)

        self._spin_interval = QSpinBox(page)
        self._spin_interval.setRange(2, 300)
        self._spin_interval.setSuffix(" 秒")
        form.addRow("刷新频率：", self._spin_interval)

        self._spin_timeout = QDoubleSpinBox(page)
        self._spin_timeout.setRange(1.0, 30.0)
        self._spin_timeout.setSingleStep(0.5)
        self._spin_timeout.setSuffix(" 秒")
        form.addRow("网络超时：", self._spin_timeout)

        hint = QLabel(
            "扩展提示：在 src/stock_window/providers/ 中新增 Provider 并注册后，\n"
            "会自动出现在上方下拉框中，无需修改 UI 代码。",
            page,
        )
        hint.setStyleSheet("color: #666666; font-size: 12px;")
        form.addRow("", hint)
        return page

    def _load_values(self, cfg: AppConfig) -> None:
        a = cfg.appearance
        if a.color_mode == ColorMode.CUSTOM_TREND.value:
            self._radio_trend.setChecked(True)
        else:
            self._radio_mono.setChecked(True)

        self._btn_mono_color.set_color(a.monochrome_color)
        self._btn_up_color.set_color(a.up_color)
        self._btn_down_color.set_color(a.down_color)
        self._btn_flat_color.set_color(a.flat_color)
        self._btn_bg_color.set_color(a.background_color)
        self._slider_bg_alpha.setValue(a.background_alpha)

        self._font_combo.setCurrentFont(QFont(a.font_family))
        self._spin_font_size.setValue(a.font_size)
        self._chk_font_bold.setChecked(a.font_bold)
        self._spin_spacing.setValue(a.item_spacing)
        self._chk_show_name.setChecked(a.show_name)
        self._chk_show_price.setChecked(a.show_price)
        self._chk_show_pct.setChecked(a.show_change_percent)
        self._chk_show_amt.setChecked(a.show_change_amount)
        self._chk_show_sign.setChecked(a.show_sign_prefix)
        self._chk_auto_prec.setChecked(a.auto_precision)

        w = cfg.window
        self._set_combo_by_data(self._combo_mode, w.mode)
        self._set_combo_by_data(self._combo_anchor, w.anchor)
        self._spin_offset_x.setValue(w.offset_x)
        self._spin_offset_y.setValue(w.offset_y)
        self._chk_locked.setChecked(w.locked)
        self._spin_max_visible.setValue(w.max_visible_items)
        self._spin_rotate.setValue(w.rotate_interval_sec)
        self._chk_fullscreen_hide.setChecked(w.hide_on_fullscreen)
        self._chk_boss_enabled.setChecked(w.boss_key_enabled)
        self._edit_boss_key.setText(w.boss_key)

        p = cfg.polling
        self._set_combo_by_data(self._combo_quote_provider, p.provider)
        self._set_combo_by_data(self._combo_search_provider, p.search_provider)
        self._spin_interval.setValue(p.interval_sec)
        self._spin_timeout.setValue(p.timeout_sec)

        self._on_color_mode_changed()

    def build_config(self) -> AppConfig:
        """收集当前界面值并构造新的 AppConfig（保留原自选股与自由悬浮坐标）。"""
        appearance = AppearanceConfig(
            color_mode=(
                ColorMode.CUSTOM_TREND.value
                if self._radio_trend.isChecked()
                else ColorMode.MONOCHROME.value
            ),
            monochrome_color=self._btn_mono_color.color,
            up_color=self._btn_up_color.color,
            down_color=self._btn_down_color.color,
            flat_color=self._btn_flat_color.color,
            background_color=self._btn_bg_color.color,
            background_alpha=self._slider_bg_alpha.value(),
            font_family=self._font_combo.currentFont().family(),
            font_size=self._spin_font_size.value(),
            font_bold=self._chk_font_bold.isChecked(),
            item_spacing=self._spin_spacing.value(),
            show_name=self._chk_show_name.isChecked(),
            show_price=self._chk_show_price.isChecked(),
            show_change_percent=self._chk_show_pct.isChecked(),
            show_change_amount=self._chk_show_amt.isChecked(),
            show_sign_prefix=self._chk_show_sign.isChecked(),
            auto_precision=self._chk_auto_prec.isChecked(),
            decimal_places=self._source_config.appearance.decimal_places,
        )
        window = WindowConfig(
            mode=str(self._combo_mode.currentData()),
            anchor=str(self._combo_anchor.currentData()),
            offset_x=self._spin_offset_x.value(),
            offset_y=self._spin_offset_y.value(),
            free_x=self._source_config.window.free_x,
            free_y=self._source_config.window.free_y,
            locked=self._chk_locked.isChecked(),
            max_visible_items=self._spin_max_visible.value(),
            rotate_interval_sec=self._spin_rotate.value(),
            hide_on_fullscreen=self._chk_fullscreen_hide.isChecked(),
            boss_key_enabled=self._chk_boss_enabled.isChecked(),
            boss_key=self._edit_boss_key.text().strip() or "Ctrl+Alt+H",
        )
        polling = PollingConfig(
            provider=str(self._combo_quote_provider.currentData() or "tencent"),
            search_provider=str(self._combo_search_provider.currentData() or "tencent"),
            interval_sec=self._spin_interval.value(),
            timeout_sec=float(self._spin_timeout.value()),
        )
        return AppConfig(
            schema_version=self._source_config.schema_version,
            stocks=self._source_config.stocks,
            appearance=appearance,
            window=window,
            polling=polling,
        )

    def _apply_mono_preset(self, hex_color: str) -> None:
        self._radio_mono.setChecked(True)
        self._btn_mono_color.set_color(hex_color)

    def _on_color_mode_changed(self) -> None:
        is_mono = self._radio_mono.isChecked()
        self._btn_mono_color.setEnabled(is_mono)
        self._btn_up_color.setEnabled(not is_mono)
        self._btn_down_color.setEnabled(not is_mono)
        self._btn_flat_color.setEnabled(not is_mono)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        cfg = self.build_config()
        a = cfg.appearance
        self._lbl_bg_alpha.setText(str(a.background_alpha))

        # 使用两条模拟涨/跌样本实时展示纯色与涨跌色差异
        sample_up_item = StockItem(symbol="sh000001", name="上证指数", alias="上证", market="SH")
        sample_up_quote = StockQuote(
            symbol="sh000001", name="上证指数", price=3582.45, prev_close=3560.00, change=22.45, change_percent=0.63
        )
        sample_down_item = StockItem(symbol="sh510300", name="沪深300ETF", alias="300E", market="SH")
        sample_down_quote = StockQuote(
            symbol="sh510300", name="沪深300ETF", price=4.052, prev_close=4.070, change=-0.018, change_percent=-0.44
        )

        v_up = self._formatter.format_item(sample_up_item, sample_up_quote, a)
        v_down = self._formatter.format_item(sample_down_item, sample_down_quote, a)

        font = QFont(a.font_family, a.font_size)
        font.setBold(a.font_bold)

        # 模拟任务栏底色（若纯色接近深黑则切换浅色模拟任务栏，避免预览看不清）
        c_mono = QColor(a.monochrome_color)
        mono_lum = 0.299 * c_mono.red() + 0.587 * c_mono.green() + 0.114 * c_mono.blue()
        base_bar_bg = "#E8EBF0" if (a.color_mode == ColorMode.MONOCHROME.value and mono_lum < 95) else "#1E1F22"
        bg_c = QColor(a.background_color)
        if a.background_alpha > 0:
            bg_css = f"rgba({bg_c.red()}, {bg_c.green()}, {bg_c.blue()}, {a.background_alpha / 255.0:.2f})"
        else:
            bg_css = base_bar_bg

        self._preview_container.setStyleSheet(
            f"background-color: {bg_css}; border: 1px solid #444444; border-radius: 4px;"
        )
        self._preview_label_up.setFont(font)
        self._preview_label_up.setText(v_up.text)
        self._preview_label_up.setStyleSheet(f"color: {v_up.color}; background: transparent; border: none;")

        self._preview_label_down.setFont(font)
        self._preview_label_down.setText(v_down.text)
        self._preview_label_down.setStyleSheet(f"color: {v_down.color}; background: transparent; border: none;")

    def _on_apply(self) -> None:
        self.config_applied.emit(self.build_config())

    def _on_accept(self) -> None:
        self.config_applied.emit(self.build_config())
        self.accept()

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
