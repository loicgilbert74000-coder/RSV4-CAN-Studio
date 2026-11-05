"""Thème sombre global (feuille de style Qt) : champs, listes déroulantes, cases, barres de défilement, boîtes de dialogue."""

from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, HOVER, MUTED, RED, SIDE, SUB, TEXT

QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root, QDialog, QMessageBox {{ background: {BG}; }}
QToolTip {{ background: {CARD2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QLineEdit, QComboBox, QSpinBox {{ background: {CARD2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {CYAN}; selection-color: {BG}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {CYAN}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {CARD2}; border: 1px solid {BORDER}; selection-background-color: {HOVER};
    outline: 0; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER}; border-radius: 4px; background: {CARD2}; }}
QCheckBox::indicator:checked {{ background: {CYAN}; border-color: {CYAN}; }}
QPushButton {{ background: {CARD2}; border: none; border-radius: 6px; padding: 7px 12px; font-weight: 600; }}
QPushButton:hover {{ background: {HOVER}; }}
QScrollBar:vertical {{ background: {BG}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #45567a; border-radius: 5px; min-height: 30px; margin: 1px; }}
QScrollBar::handle:vertical:hover {{ background: #6a80ad; }}
QScrollBar:horizontal {{ background: {BG}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #45567a; border-radius: 5px; min-width: 30px; margin: 1px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFormLayout QLabel {{ color: {SUB}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {CARD}; top: -1px; }}
QTabBar::tab {{ background: {CARD2}; color: {SUB}; padding: 8px 16px; margin-right: 3px; border-top-left-radius: 6px;
    border-top-right-radius: 6px; font-weight: 700; }}
QTabBar::tab:selected {{ background: {CARD}; color: {TEXT}; border-bottom: 2px solid {CYAN}; }}
QTabBar::tab:hover {{ background: {HOVER}; }}
QTableWidget, QTableView {{ background: {CARD}; color: {TEXT}; gridline-color: {BORDER}; border: none; font-size: 13px;
    selection-background-color: {HOVER}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: {CARD2}; color: {SUB}; border: none; border-right: 1px solid {BORDER}; padding: 6px;
    font-weight: 700; }}
QListWidget {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; }}
QDialog {{ background: {BG}; }}
QMenu {{ background: {CARD2}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {HOVER}; }}
"""
