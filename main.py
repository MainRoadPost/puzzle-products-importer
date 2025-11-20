#!/usr/bin/env python3

# Главный модуль приложения для импорта продуктов в систему Puzzle
# Обеспечивает интеграцию UI и API для загрузки данных из CSV файлов

import dotenv
import os
import sys
import logging
import asyncio
from typing import TypedDict, Any
from collections.abc import Coroutine

from PyQt5.QtWidgets import QApplication
from PyQt5 import QtGui
from qasync import QEventLoop, asyncSlot  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]

# Импортируем асинхронный клиент Puzzle и связанные классы
from puzzle.client import Client, ProductAdd, ProductChange
from puzzle.enums import ProductKind
from puzzle.exceptions import GraphQLClientGraphQLError, GraphQLClientHttpError
from puzzle.input_types import StringsUpdate

# Импортируем локальные модули
from ui_layout import PuzzleUploaderUI
from csv_handler import ProductNode, ProductGroupNode, parse_csv_file


# URL API Puzzle (можно переключать между локальным и продакшн серверами)
PUZZLE_API = "http://localhost:8000/api/graphql"
# PUZZLE_API = "https://puzzle.mrpost.ru/api/graphql"
# PUZZLE_API = "https://cubic.pzzle.ru/api/graphql"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")


# TypedDict для описания существующего элемента в системе
class ExistingItem(TypedDict):
    kind: str
    id: str
    code: str
    parentId: str | None


class PuzzleImporter:
    """Обрабатывает взаимодействие с Puzzle API для импорта продуктов.

    Класс отвечает за:
    - Авторизацию в системе Puzzle
    - Получение списка доменов и проектов
    - Импорт продуктов из CSV файлов
    - Обновление существующих продуктов
    - Создание групп и продуктов через GraphQL API
    """

    def __init__(self, api_url: str, ui: PuzzleUploaderUI):
        self.client = Client(url=api_url)
        self.ui = ui
        self.selected_project_id: str | None = None
        self.csv_file_path: str | None = None
        self.update_mode = False

    @asyncSlot()
    async def get_domains(self):
        """Получает список доменов через GraphQL клиент."""
        try:
            response = await self.client.get_domains()
            self.ui.domain_combo.clear()
            self.ui.domain_combo.addItem("No domain", None)
            for domain in response.domains:
                self.ui.domain_combo.addItem(domain.name, domain.name)
            if os.environ.get("PUZZLE_USER_DOMAIN"):
                index = self.ui.domain_combo.findData(os.environ["PUZZLE_USER_DOMAIN"])
                if index != -1:
                    self.ui.domain_combo.setCurrentIndex(index)
            if os.environ.get("PUZZLE_USERNAME"):
                self.ui.login_input.setText(os.environ["PUZZLE_USERNAME"])
            if os.environ.get("PUZZLE_PASSWORD"):
                self.ui.password_input.setText(os.environ["PUZZLE_PASSWORD"])
            logging.info("Domain list updated.")
        except Exception as e:
            logging.error(f"Error fetching domains: {e}")
            self.ui.login_status_label.setText(f"Error: {e}")

    @asyncSlot()
    async def attempt_login(self):
        """Выполняет попытку входа в систему используя GraphQL клиент."""
        domain_name = self.ui.domain_combo.currentData()
        username = self.ui.login_input.text().strip()
        password = self.ui.password_input.text()

        # Проверяем наличие всех необходимых данных
        if not all([username, password]):
            self.ui.login_status_label.setText(
                "Please provide domain, login, and password."
            )
            logging.warning("Login failed: Missing credentials.")
            return

        self.ui.login_status_label.setText(
            f"Attempting login to {self.ui.domain_combo.currentText()}..."
        )

        try:
            response = await self.client.login(
                domain_name=domain_name, username=username, password=password
            )

            if response.login:
                logging.info("Login successful.")
                # Клиент автоматически управляет сессией и cookies
                self.ui.login_status_label.setText(
                    "Login successful. Fetching projects..."
                )
                await self.fetch_projects()
            else:
                logging.error("Login failed.")
                self.ui.login_status_label.setText("Login failed.")
        except Exception as e:
            logging.error(f"Login failed: {e}")
            self.ui.login_status_label.setText(f"Login failed: {e}")

    @asyncSlot()
    async def fetch_projects(self):
        """Получает список проектов используя GraphQL клиент."""
        try:
            response = await self.client.get_projects()
            if response.projects:
                # Фильтруем только активные проекты (не завершённые)
                active_projects = [p for p in response.projects if p.done_at is None]

                self.ui.project_combo.clear()
                for project in active_projects:
                    self.ui.project_combo.addItem(project.title, project.id)

                if active_projects:
                    self.ui.project_combo.setEnabled(True)
                    self.ui.login_status_label.setText(
                        "Projects loaded. Please select a project."
                    )
                    logging.info("Projects loaded successfully.")
                else:
                    self.ui.login_status_label.setText("No active projects available.")
                    logging.info("No active projects found.")
            else:
                self.ui.login_status_label.setText("Failed to fetch projects.")
                logging.error("Failed to fetch projects.")
        except Exception as e:
            logging.error(f"Error fetching projects: {e}")
            self.ui.login_status_label.setText(f"Error: {e}")

    @asyncSlot()
    async def start_import(self):
        """Запускает процесс импорта при нажатии кнопки импорта."""
        self.csv_file_path = self.ui.csv_file_path
        if not self.csv_file_path:
            self.ui.import_status_label.setText(
                "Please select a CSV file before importing."
            )
            logging.warning("Start import failed: No CSV file selected.")
            return

        self.selected_project_id = self.ui.project_combo.currentData()
        if not self.selected_project_id:
            self.ui.import_status_label.setText(
                "Please select a project before importing."
            )
            logging.warning("Start import failed: No project selected.")
            return

        logging.info(f"Starting import for CSV file: {self.csv_file_path}")
        logging.info(f"Selected project ID: {self.selected_project_id}")
        self.ui.import_status_label.setText("Import started...")

        # Сохраняем режим обновления (update mode)
        self.update_mode = self.ui.update_mode_checkbox.isChecked()

        # Парсим CSV файл
        root_node = parse_csv_file(self.csv_file_path)

        if root_node:
            logging.info("CSV parsed successfully.")
            self.ui.import_status_label.setText(
                "CSV parsed successfully. Starting import..."
            )

            # Генерируем и выполняем mutation запросы
            await self.generate_mutation_queries(root_node)
            self.ui.import_status_label.setText("Import completed successfully.")
            logging.info("Import completed successfully.")
        else:
            self.ui.import_status_label.setText("Error: Failed to parse the CSV file.")
            logging.error("Import failed: Failed to parse the CSV file.")

    async def generate_mutation_queries(
        self, root: ProductGroupNode, parent_id: str | None = None
    ):
        """Рекурсивно генерирует и выполняет mutation запросы.

        Args:
            root (ProductGroupNode): Корневой узел дерева продуктов.
            parent_id (str, optional): ID родительского узла в API.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for import.")
            return

        for child_name, child_node in root.children.items():
            self.ui.import_status_label.setText(f"Importing '{child_name}'...")
            logging.info(f"Processing '{child_name}'...")
            logging.debug(f"Child node details: {child_node}")

            # Проверяем, существует ли элемент с таким именем
            existing_item = await self.check_if_exists(
                self.selected_project_id, child_name, parent_id
            )

            if existing_item:
                # Определяем ожидаемый тип элемента
                child_kind = (
                    ProductKind.GROUP
                    if isinstance(child_node, ProductGroupNode)
                    else ProductKind.PRODUCT
                )
                # Проверяем соответствие типов
                if existing_item["kind"] != child_kind:
                    logging.warning(
                        f"Conflict: '{child_name}' is a {existing_item['kind']} but expected {child_kind}."
                    )
                    continue
                # В режиме обновления обновляем продукт
                if self.update_mode and isinstance(child_node, ProductNode):
                    await self.update_product(child_node, existing_item["id"])
                    continue
                else:
                    logging.info(
                        f"{child_name} already exists as {child_kind}. Skipping creation."
                    )
                    # Для групп рекурсивно обрабатываем дочерние элементы
                    if isinstance(child_node, ProductGroupNode):
                        await self.generate_mutation_queries(
                            child_node, existing_item["id"]
                        )
                    continue

            if isinstance(child_node, ProductGroupNode):
                # Создаём группу продуктов
                new_parent_id = await self.create_product_group(child_node, parent_id)
                if new_parent_id:
                    await self.generate_mutation_queries(
                        child_node, parent_id=new_parent_id
                    )
            else:
                # Создаём продукт
                await self.create_product(child_node, parent_id)

    ####

    async def create_product_group(self, node: ProductGroupNode, parent_id: str | None):
        """Создаёт группу продуктов через GraphQL mutation.

        Args:
            node (ProductGroupNode): Узел, представляющий группу продуктов.
            parent_id (str): ID родительского узла.

        Returns:
            str: ID новой созданной группы, или None если создание не удалось.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for creating product group.")
            return None

        product_input = ProductAdd(
            projectId=self.selected_project_id,
            parentId=parent_id,
            code=node.name,
            kind=ProductKind.GROUP,
            description=None,
            tags=[],
        )

        try:
            if self.ui.dry_run_checkbox.isChecked():
                logging.debug(
                    f"[Dry run] Prepared to create product group: {product_input}"
                )
                logging.info(f"[Dry run] Skipping creation of group '{node.name}'.")
                return None
            response = await self.client.create_product_group(product_input)
            if response.product_create and response.product_create.id:
                group_id = response.product_create.id
                logging.info(
                    f"Group '{node.name}' created successfully with ID {group_id}."
                )
                return group_id
            else:
                logging.warning(f"Failed to create group '{node.name}'.")
                return None
        except Exception as e:
            logging.error(f"Error creating group '{node.name}': {e}")
            return None

    async def create_product(self, node: ProductNode, parent_id: str | None):
        """Создаёт продукт через GraphQL mutation.

        Args:
            node (ProductNode): Узел, представляющий продукт.
            parent_id (str): ID родительского узла.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for creating product.")
            return

        if self.csv_file_path is None:
            logging.warning("No csv file selected, skipping")
            return

        # Подготавливаем данные продукта для создания
        product_add = ProductAdd(
            projectId=self.selected_project_id,
            parentId=parent_id,
            status=node.product_data.status,
            dueDate=node.product_data.due,
            estimation=node.product_data.awarded,
            deliverable=node.product_data.deliverable,
            code=node.name,
            kind=ProductKind.PRODUCT,
            # description=description,
            thumbnail=node.product_data.thumbnail_upload,
            tags=node.product_data.tags,
        )

        # Пытаемся создать продукт
        try:
            if self.ui.dry_run_checkbox.isChecked():
                logging.debug(f"[Dry run] Prepared to create product: {product_add}")
                logging.info(f"[Dry run] Skipping creation of product '{node.name}'.")
                return
            response = await self.client.create_product(product_add)
            if response.product_create and response.product_create.id:
                product_id = response.product_create.id
                logging.info(
                    f"Product '{node.name}' created successfully with ID {product_id}."
                )
            else:
                logging.warning(f"Failed to create product '{node.name}'.")

        except GraphQLClientGraphQLError as e:
            logging.error(f"Error creating product '{node.name}': {e.message}")
        except GraphQLClientHttpError as e:
            logging.error(
                f"HTTP error creating product '{node.name}': {e.response.text}"
            )

    async def update_product(self, node: ProductNode, existing_id: str):
        """Обновляет существующий продукт через GraphQL mutation.

        Args:
            node (ProductNode): Узел с новыми данными продукта.
            existing_id (str): ID существующего продукта.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for updating product.")
            return

        if self.csv_file_path is None:
            logging.warning("No csv file selected, skipping")
            return

        try:
            if self.ui.dry_run_checkbox.isChecked():
                logging.debug(f"[Dry run] Prepared to update product ID {existing_id}")
                logging.info(f"[Dry run] Skipping update of product '{node.name}'.")
                return
            # Подготавливаем изменения
            change = ProductChange(
                status=node.product_data.status,
                dueDate=node.product_data.due,
                estimation=node.product_data.awarded,
                deliverable=node.product_data.deliverable,
                thumbnail=node.product_data.thumbnail_upload,
                tags=StringsUpdate(set=node.product_data.tags),
            )
            # Обновляем продукт (один продукт за раз для корректной передачи изображения)
            resp = await self.client.update_products(
                project_id=self.selected_project_id,
                product_ids=[existing_id],
                change=change,
            )
            if resp.products_update:
                logging.info(f"{node.name} updated")
        except Exception as e:
            logging.error(f"Failed to update {node.name}: {e}")

    async def check_if_exists(
        self, project_id: str, code: str, parent_id: str | None
    ) -> ExistingItem | None:
        """Проверяет, существует ли продукт или группа с заданным кодом.

        Args:
            code (str): Код продукта или группы.
            parent_id (str): ID родительского узла.

        Returns:
            dict: Данные существующего элемента если найден, иначе None.
        """
        logging.info(f"Checking if '{code}' exists under parent {parent_id or 'root'}.")

        parent_ids = [parent_id] if parent_id else []

        try:
            response = await self.client.get_product_descendants(
                project_id, parent_ids, 1
            )
            if response.product_descendants:
                for descendant in response.product_descendants:
                    if descendant.code == code:
                        logging.info(
                            f"Found existing {descendant.kind} with code '{code}'."
                        )
                        return {
                            "kind": descendant.kind,
                            "id": descendant.id,
                            "code": descendant.code,
                            "parentId": descendant.parent_id,
                        }
            else:
                logging.info(f"No existing item found for code '{code}'.")
            return None
        except Exception as e:
            logging.error(f"Error checking existence of '{code}': {e}")
            return None

    # Переопределяем обработчик закрытия окна
    def closeEvent(self, a0: QtGui.QCloseEvent | None) -> None:
        """Обработчик события закрытия окна приложения."""
        logging.info("Окно закрывается, останавливаем event loop...")
        loop = asyncio.get_event_loop()
        loop.stop()  # Останавливаем цикл событий asyncio
        if a0:
            a0.accept()  # Завершаем событие закрытия окна

    def schedule_async(self, coro: Coroutine[Any, Any, None]) -> None:
        """Планирует выполнение асинхронной корутины в event loop."""
        asyncio.ensure_future(coro)


class PuzzleUploaderApp:
    """Главный класс приложения, связывающий UI и импортер."""

    def __init__(self):
        self.app = QApplication(sys.argv)

        # Создаём event loop
        self.loop = QEventLoop(self.app)
        asyncio.set_event_loop(self.loop)

        # Создаём UI
        self.ui = PuzzleUploaderUI(self.schedule_async)

        # Создаём импортер
        self.importer = PuzzleImporter(PUZZLE_API, self.ui)

        # Связываем сигналы UI с методами импортера
        self.connect_signals()

        # Инициализация - загружаем список доменов
        self.schedule_async(self.importer.get_domains())

    def connect_signals(self):
        """Связывает клики по кнопкам UI с методами импортера."""
        self.ui.login_button.clicked.connect(
            lambda: self.schedule_async(self.importer.attempt_login())
        )
        self.ui.csv_button.clicked.connect(self.ui.open_file_dialog)
        self.ui.import_button.clicked.connect(
            lambda: self.schedule_async(self.importer.start_import())
        )

    def schedule_async(self, coro: Coroutine[Any, Any, None]) -> None:
        """Планирует выполнение асинхронной корутины в event loop."""
        asyncio.ensure_future(coro)

    def run(self):
        """Запускает приложение."""
        self.ui.show()

        with self.loop:
            try:
                self.loop.run_forever()
            except KeyboardInterrupt:
                pass

        return 0


if __name__ == "__main__":
    dotenv.load_dotenv()
    if os.environ.get("LOG_LEVEL"):
        log_level = os.environ["LOG_LEVEL"].upper()
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))
    app = PuzzleUploaderApp()
    sys.exit(app.run())
