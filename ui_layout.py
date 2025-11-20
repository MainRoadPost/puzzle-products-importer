"""UI макет и компоненты приложения Puzzle Uploader.

Модуль содержит определение пользовательского интерфейса на основе PyQt5.
Включает в себя:
- Форму авторизации
- Выбор проекта
- Загрузку CSV файлов
- Контроль процесса импорта
- Отладочный режим для работы с GraphQL запросами
"""

import logging
from typing import Any
from collections.abc import Callable, Coroutine

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QComboBox,
    QTextEdit,
    QCheckBox,
)
from PyQt5.QtCore import Qt


class PuzzleUploaderUI(QWidget):
    """Главное окно приложения Puzzle Uploader.

    Предоставляет графический интерфейс для:
    - Авторизации в системе Puzzle
    - Выбора проекта
    - Загрузки CSV файлов с продуктами
    - Запуска импорта
    - Отладки GraphQL запросов
    """

    def __init__(
        self, schedule_async_callback: Callable[[Coroutine[Any, Any, None]], None]
    ):
        """
        Инициализирует UI.

        Args:
            schedule_async_callback: Функция обратного вызова для планирования асинхронных корутин
        """
        super().__init__()

        self.schedule_async = schedule_async_callback

        # Устанавливаем заголовок окна
        self.setWindowTitle("Puzzle Uploader")

        # Создаём layout
        self.ui_layout = QVBoxLayout()
        self.ui_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(self.ui_layout)

        # Инициализируем компоненты UI
        self.init_ui()

        # Инициализируем переменные
        self.csv_file_path: str | None = None

    def init_ui(self):
        """Инициализирует компоненты UI."""
        self.init_login_section()
        self.init_project_section()
        self.init_file_section()
        self.init_import_section()
        self.init_debug_section()

    def init_login_section(self):
        """Инициализирует секцию авторизации в UI."""
        # Выбор домена
        self.domain_label = QLabel("Domain:")
        self.domain_combo = QComboBox()
        self.ui_layout.addWidget(self.domain_label)
        self.ui_layout.addWidget(self.domain_combo)

        # Поле ввода логина
        self.login_label = QLabel("Login:")
        self.login_input = QLineEdit()
        self.ui_layout.addWidget(self.login_label)
        self.ui_layout.addWidget(self.login_input)

        # Поле ввода пароля
        self.password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ui_layout.addWidget(self.password_label)
        self.ui_layout.addWidget(self.password_input)

        # Кнопка входа
        self.login_button = QPushButton("Login")
        self.ui_layout.addWidget(self.login_button)

        # Метка статуса входа
        self.login_status_label = QLabel("Please login to continue")
        self.ui_layout.addWidget(self.login_status_label)

    def init_project_section(self):
        """Инициализирует секцию выбора проекта."""
        # Комбобокс для выбора проекта
        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)
        self.ui_layout.addWidget(self.project_combo)

    def init_file_section(self):
        """Инициализирует секцию выбора файла."""
        # Кнопка выбора CSV файла
        self.csv_button = QPushButton("Select CSV File")
        self.ui_layout.addWidget(self.csv_button)

        # Метка с путём к выбранному файлу
        self.csv_label = QLabel("No file selected")
        self.ui_layout.addWidget(self.csv_label)

    def init_import_section(self):
        """Инициализирует секцию импорта."""

        # Кнопка запуска импорта
        self.import_button = QPushButton("Start Import")
        self.import_button.setEnabled(False)
        self.ui_layout.addWidget(self.import_button)

        # Чекбокс режима обновления (Update mode)
        self.update_mode_checkbox = QCheckBox("Update")
        self.update_mode_checkbox.setChecked(False)  # По умолчанию выключен
        self.ui_layout.addWidget(self.update_mode_checkbox)

        # Метка статуса импорта
        self.import_status_label = QLabel("")
        self.ui_layout.addWidget(self.import_status_label)

    def init_debug_section(self):
        """Инициализирует секцию отладки."""
        # Чекбокс режима отладки
        self.debug_mode_checkbox = QCheckBox("Debug mode")
        self.debug_mode_checkbox.setChecked(False)
        self.debug_mode_checkbox.stateChanged.connect(self.toggle_debug_mode)
        self.ui_layout.addWidget(self.debug_mode_checkbox)

        # Чекбокс dry run режима
        self.dry_run_checkbox = QCheckBox("Dry run")
        self.dry_run_checkbox.setChecked(False)
        self.ui_layout.addWidget(self.dry_run_checkbox)

        # Поле ввода GraphQL запроса
        self.graphql_request_label = QLabel("GraphQL Request:")
        self.graphql_request_input = QTextEdit()

        # Кнопка отправки GraphQL запроса
        self.send_graphql_button = QPushButton("Send GraphQL Request")
        # self.send_graphql_button.clicked.connect(self.send_graphql_request)

        # Поле вывода ответа GraphQL
        self.graphql_response_label = QLabel("GraphQL Response:")
        self.graphql_response_output = QTextEdit()
        self.graphql_response_output.setReadOnly(True)

        # Изначально скрываем виджеты отладки
        self.set_debug_widgets_visibility(False)

        # Добавляем виджеты отладки в layout
        self.ui_layout.addWidget(self.graphql_request_label)
        self.ui_layout.addWidget(self.graphql_request_input)
        self.ui_layout.addWidget(self.send_graphql_button)
        self.ui_layout.addWidget(self.graphql_response_label)
        self.ui_layout.addWidget(self.graphql_response_output)

    def set_debug_widgets_visibility(self, visible: bool):
        """Показывает или скрывает виджеты отладки на основе параметра 'visible'."""
        widgets: list[QWidget] = [
            self.graphql_request_label,
            self.graphql_request_input,
            self.send_graphql_button,
            self.graphql_response_label,
            self.graphql_response_output,
        ]
        for widget in widgets:
            widget.setVisible(visible)

    def toggle_debug_mode(self):
        """Показывает или скрывает виджеты отладки на основе состояния чекбокса."""
        is_checked = self.debug_mode_checkbox.isChecked()
        self.set_debug_widgets_visibility(is_checked)
        self.adjustSize()

    def open_file_dialog(self):
        """Открывает диалог выбора CSV файла."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File",
            "",
            "CSV Files (*.csv);;All Files (*)",
            options=options,
        )
        if file_path:
            self.csv_label.setText(file_path)
            self.csv_file_path = file_path
            self.import_button.setEnabled(True)
            logging.info(f"CSV file selected: {file_path}")
        else:
            self.csv_label.setText("No file selected")
            self.csv_file_path = None
            self.import_button.setEnabled(False)
            logging.info("No CSV file selected.")
