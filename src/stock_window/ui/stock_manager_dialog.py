"""自选管理弹窗：支持中文名称 / 拼音首字母 / 代码实时防抖搜索、排序与低调别名配置。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stock_window.models.stock import SearchResult, StockItem


class _SearchSignals(QObject):
    """后台搜索线程回传给 UI 线程的信号载体。"""

    finished = Signal(int, list)
    failed = Signal(int, str)


class _SearchWorker(QRunnable):
    """在线程池中执行搜索请求，避免输入关键词时卡顿界面。"""

    def __init__(
        self,
        request_id: int,
        keyword: str,
        search_fn: Callable[[str], list[SearchResult]],
        signals: _SearchSignals,
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._keyword = keyword
        self._search_fn = search_fn
        self._signals = signals

    def run(self) -> None:
        try:
            results = self._search_fn(self._keyword)
            self._signals.finished.emit(self._request_id, results)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(self._request_id, str(exc))


class StockManagerDialog(QDialog):
    """管理自选股列表：搜索添加、上下排序、显示开关与自定义低调简称。"""

    def __init__(
        self,
        stocks: list[StockItem],
        search_fn: Callable[[str], list[SearchResult]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("自选股管理 - StockWindow")
        self.resize(680, 560)

        self._search_fn = search_fn
        self._items: list[StockItem] = [StockItem.from_dict(s.to_dict()) for s in stocks]
        self._thread_pool = QThreadPool.globalInstance()
        self._search_seq = 0

        # 300ms 输入防抖计时器：用户连续打字时不反复打接口
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._execute_search)

        self._build_ui()
        self._refresh_watchlist_table()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- 顶部：模糊搜索区 ----
        search_header = QLabel("添加股票（支持中文名称、拼音首字母或代码，无需记忆市场前缀）：", self)
        root.addWidget(search_header)

        search_row = QHBoxLayout()
        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("例如：茅台 / gzmt / 腾讯 / 苹果 / 沪深300 / 510300")
        self._search_input.textChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self._search_input, 1)

        self._btn_add_selected = QPushButton("添加选中候选", self)
        self._btn_add_selected.clicked.connect(self._add_selected_candidate)
        search_row.addWidget(self._btn_add_selected)
        root.addLayout(search_row)

        self._search_status = QLabel("输入关键词后自动搜索（双击候选可直接加入自选）", self)
        self._search_status.setStyleSheet("color: #666666; font-size: 12px;")
        root.addWidget(self._search_status)

        self._candidate_list = QListWidget(self)
        self._candidate_list.setMaximumHeight(160)
        self._candidate_list.itemDoubleClicked.connect(self._on_candidate_double_clicked)
        root.addWidget(self._candidate_list)

        # ---- 手动输入代码兜底行 ----
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("或手动输入代码：", self))
        self._manual_symbol = QLineEdit(self)
        self._manual_symbol.setPlaceholderText("标准代码如 sh000001 / hk00700 / usAAPL")
        manual_row.addWidget(self._manual_symbol, 1)
        self._manual_name = QLineEdit(self)
        self._manual_name.setPlaceholderText("名称或简称（可选）")
        self._manual_name.setMaximumWidth(160)
        manual_row.addWidget(self._manual_name)
        btn_manual_add = QPushButton("直接添加", self)
        btn_manual_add.clicked.connect(self._add_manual_symbol)
        manual_row.addWidget(btn_manual_add)
        root.addLayout(manual_row)

        # ---- 中部：当前自选表格 ----
        watchlist_label = QLabel(
            "当前自选列表（双击「低调简称」列可自定义任务栏显示文字，留空则显示官方名称）：",
            self,
        )
        root.addWidget(watchlist_label)

        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(["显示", "官方名称", "低调简称（可编辑）", "代码", "市场"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemChanged.connect(self._on_table_item_changed)
        root.addWidget(self._table, 1)

        # ---- 排序与删除操作栏 ----
        action_row = QHBoxLayout()
        btn_up = QPushButton("上移", self)
        btn_up.clicked.connect(lambda: self._move_selected(-1))
        btn_down = QPushButton("下移", self)
        btn_down.clicked.connect(lambda: self._move_selected(1))
        btn_remove = QPushButton("删除选中", self)
        btn_remove.clicked.connect(self._remove_selected)
        action_row.addWidget(btn_up)
        action_row.addWidget(btn_down)
        action_row.addWidget(btn_remove)
        action_row.addStretch(1)
        root.addLayout(action_row)

        # ---- 底部确认按钮 ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_stocks(self) -> list[StockItem]:
        """返回用户编辑后的自选股列表副本。"""
        return [StockItem.from_dict(item.to_dict()) for item in self._items]

    def _on_search_text_changed(self, text: str) -> None:
        keyword = text.strip()
        if not keyword:
            self._debounce_timer.stop()
            self._candidate_list.clear()
            self._search_status.setText("输入关键词后自动搜索（双击候选可直接加入自选）")
            return
        self._search_status.setText("搜索中...")
        self._debounce_timer.start()

    def _execute_search(self) -> None:
        keyword = self._search_input.text().strip()
        if not keyword:
            return
        self._search_seq += 1
        seq = self._search_seq

        signals = _SearchSignals()
        signals.finished.connect(self._on_search_finished)
        signals.failed.connect(self._on_search_failed)
        worker = _SearchWorker(seq, keyword, self._search_fn, signals)
        # 将信号对象挂到 worker 避免提前被垃圾回收
        worker._signals_ref = signals  # type: ignore[attr-defined]
        self._thread_pool.start(worker)

    def _on_search_finished(self, request_id: int, results: list[SearchResult]) -> None:
        # 丢弃过期的旧搜索响应（防乱序覆盖最新输入结果）
        if request_id != self._search_seq:
            return
        self._candidate_list.clear()
        if not results:
            self._search_status.setText("未找到匹配标的，可尝试更换关键词或直接输入标准代码。")
            return

        self._search_status.setText(f"找到 {len(results)} 条匹配结果（双击或点按钮添加）：")
        for res in results:
            label = f"[{res.security_type or res.market}]  {res.name}   ({res.symbol})"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, res)
            self._candidate_list.addItem(list_item)
        self._candidate_list.setCurrentRow(0)

    def _on_search_failed(self, request_id: int, message: str) -> None:
        if request_id != self._search_seq:
            return
        self._search_status.setText(f"搜索失败：{message}")

    def _on_candidate_double_clicked(self, list_item: QListWidgetItem) -> None:
        res: SearchResult | None = list_item.data(Qt.ItemDataRole.UserRole)
        if res is not None:
            self._append_stock_item(res.to_stock_item())

    def _add_selected_candidate(self) -> None:
        current = self._candidate_list.currentItem()
        if current is None:
            return
        res: SearchResult | None = current.data(Qt.ItemDataRole.UserRole)
        if res is not None:
            self._append_stock_item(res.to_stock_item())

    def _add_manual_symbol(self) -> None:
        symbol = self._manual_symbol.text().strip()
        if not symbol:
            return
        name = self._manual_name.text().strip() or symbol
        market = symbol[:2].upper() if len(symbol) >= 3 and symbol[:2].isalpha() else ""
        self._append_stock_item(StockItem(symbol=symbol, name=name, alias="", market=market, visible=True))
        self._manual_symbol.clear()
        self._manual_name.clear()

    def _append_stock_item(self, item: StockItem) -> None:
        if any(existing.symbol.lower() == item.symbol.lower() for existing in self._items):
            QMessageBox.information(self, "已在自选列表中", f"{item.name} ({item.symbol}) 已存在，无需重复添加。")
            return
        self._items.append(item)
        self._refresh_watchlist_table()
        self._table.selectRow(len(self._items) - 1)

    def _refresh_watchlist_table(self) -> None:
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(len(self._items))
            for row, item in enumerate(self._items):
                # 列 0：是否显示在任务栏
                chk_container = QWidget(self._table)
                chk_layout = QHBoxLayout(chk_container)
                chk_layout.setContentsMargins(0, 0, 0, 0)
                chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox = QCheckBox(chk_container)
                checkbox.setChecked(item.visible)
                checkbox.stateChanged.connect(
                    lambda state, r=row: self._on_visible_toggled(r, state == Qt.CheckState.Checked.value)
                )
                chk_layout.addWidget(checkbox)
                self._table.setCellWidget(row, 0, chk_container)

                # 列 1：官方名称（只读）
                name_cell = QTableWidgetItem(item.name)
                name_cell.setFlags(name_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, 1, name_cell)

                # 列 2：低调简称（允许双击直接编辑）
                alias_cell = QTableWidgetItem(item.alias)
                self._table.setItem(row, 2, alias_cell)

                # 列 3：代码（只读）
                sym_cell = QTableWidgetItem(item.symbol)
                sym_cell.setFlags(sym_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, 3, sym_cell)

                # 列 4：市场（只读）
                mkt_cell = QTableWidgetItem(item.market)
                mkt_cell.setFlags(mkt_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, 4, mkt_cell)
        finally:
            self._table.blockSignals(False)

    def _on_visible_toggled(self, row: int, checked: bool) -> None:
        if 0 <= row < len(self._items):
            self._items[row].visible = checked

    def _on_table_item_changed(self, table_item: QTableWidgetItem) -> None:
        row = table_item.row()
        col = table_item.column()
        if col == 2 and 0 <= row < len(self._items):
            self._items[row].alias = table_item.text().strip()

    def _move_selected(self, delta: int) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        target = row + delta
        if not (0 <= target < len(self._items)):
            return
        self._items[row], self._items[target] = self._items[target], self._items[row]
        self._refresh_watchlist_table()
        self._table.selectRow(target)

    def _remove_selected(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._items):
            self._items.pop(row)
            self._refresh_watchlist_table()
            if self._items:
                self._table.selectRow(min(row, len(self._items) - 1))
