#!/usr/bin/env python3

import sys
import logging
import asyncio
from typing import TypedDict, Any
from collections.abc import Coroutine

from PyQt5.QtWidgets import QApplication
from PyQt5 import QtGui
from qasync import QEventLoop, asyncSlot  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]

# Import the async PuzzleClient and related classes and methods
from puzzle.client import Client, ProductAdd, ProductChange
from puzzle.enums import ProductKind
from puzzle.exceptions import GraphQLClientGraphQLError, GraphQLClientHttpError
from puzzle.input_types import StringsUpdate

# Import local modules
from ui_layout import PuzzleUploaderUI
from csv_handler import ProductNode, ProductGroupNode, parse_csv_file


PUZZLE_API = "http://localhost:8000/api/graphql"
# PUZZLE_API = "https://puzzle.mrpost.ru/api/graphql"
# PUZZLE_API = "https://cubic.pzzle.ru/api/graphql"

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")


class ExistingItem(TypedDict):
    kind: str
    id: str
    code: str
    parentId: str | None


class PuzzleImporter:
    """Handles the interaction with Puzzle API for importing products."""

    def __init__(self, api_url: str, ui: PuzzleUploaderUI):
        self.client = Client(url=api_url)
        self.ui = ui
        self.selected_project_id: str | None = None
        self.csv_file_path: str | None = None
        self.update_mode = False

    @asyncSlot()
    async def get_domains(self):
        """Fetches the list of domains via the generated GraphQL client."""
        try:
            response = await self.client.get_domains()
            self.ui.domain_combo.clear()
            self.ui.domain_combo.addItem("No domain", None)
            for domain in response.domains:
                self.ui.domain_combo.addItem(domain.name, domain.name)
            logging.info("Domain list updated.")
        except Exception as e:
            logging.error(f"Error fetching domains: {e}")
            self.ui.login_status_label.setText(f"Error: {e}")

    @asyncSlot()
    async def attempt_login(self):
        """Attempts to log in using the generated GraphQL client."""
        domain_name = self.ui.domain_combo.currentData()
        username = self.ui.login_input.text().strip()
        password = self.ui.password_input.text()

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
                # The client should manage the session and cookies automatically
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
        """Fetches the list of projects using the generated GraphQL client."""
        try:
            response = await self.client.get_projects()
            if response.projects:
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
        """Starts the import process when the import button is clicked."""
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

        # store update mode
        self.update_mode = self.ui.update_mode_checkbox.isChecked()

        # Parse CSV file
        root_node = parse_csv_file(self.csv_file_path)

        if root_node:
            logging.info("CSV parsed successfully.")
            self.ui.import_status_label.setText(
                "CSV parsed successfully. Starting import..."
            )

            # Generate and execute mutation queries
            await self.generate_mutation_queries(root_node)
            self.ui.import_status_label.setText("Import completed successfully.")
            logging.info("Import completed successfully.")
        else:
            self.ui.import_status_label.setText("Error: Failed to parse the CSV file.")
            logging.error("Import failed: Failed to parse the CSV file.")

    async def generate_mutation_queries(
        self, root: ProductGroupNode, parent_id: str | None = None
    ):
        """Recursively generates and executes mutation queries.

        Args:
            root (ProductGroupNode): The root node of the product tree.
            parent_id (str, optional): The ID of the parent node in the API.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for import.")
            return

        for child_name, child_node in root.children.items():
            self.ui.import_status_label.setText(f"Importing '{child_name}'...")

            existing_item = await self.check_if_exists(
                self.selected_project_id, child_name, parent_id
            )

            if existing_item:
                child_kind = (
                    ProductKind.GROUP
                    if isinstance(child_node, ProductGroupNode)
                    else ProductKind.PRODUCT
                )
                if existing_item["kind"] != child_kind:
                    logging.warning(
                        f"Conflict: '{child_name}' is a {existing_item['kind']} but expected {child_kind}."
                    )
                    continue
                if self.update_mode and isinstance(child_node, ProductNode):
                    await self.update_product(child_node, existing_item["id"])
                    continue
                else:
                    logging.info(
                        f"{child_name} already exists as {child_kind}. Skipping creation."
                    )
                    if isinstance(child_node, ProductGroupNode):
                        await self.generate_mutation_queries(
                            child_node, existing_item["id"]
                        )
                    continue

            if isinstance(child_node, ProductGroupNode):
                # Create product group
                new_parent_id = await self.create_product_group(child_node, parent_id)
                if new_parent_id:
                    await self.generate_mutation_queries(
                        child_node, parent_id=new_parent_id
                    )
            else:
                # Create product
                await self.create_product(child_node, parent_id)

    ####

    async def create_product_group(self, node: ProductGroupNode, parent_id: str | None):
        """Creates a product group via GraphQL mutation.

        Args:
            node (ProductGroupNode): The node representing the product group.
            parent_id (str): The ID of the parent node.

        Returns:
            str: The ID of the newly created group, or None if creation failed.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for creating product group.")
            return None

        product_input = ProductAdd(
            projectId=self.selected_project_id,
            parentId=parent_id,
            code=node.name,
            kind=ProductKind.GROUP,
            description={"ops": []},
            tags=[],
        )

        try:
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
        """Creates a product via GraphQL mutation.

        Args:
            node (ProductTreeNode): The node representing the product.
            parent_id (str): The ID of the parent node.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for creating product.")
            return

        if self.csv_file_path is None:
            logging.warning("No csv file selected, skipping")
            return

        # Prepare product input data
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

        # Now try to create the product
        try:
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
        if self.selected_project_id is None:
            logging.error("No project selected for updating product.")
            return

        if self.csv_file_path is None:
            logging.warning("No csv file selected, skipping")
            return

        try:
            change = ProductChange(
                status=node.product_data.status,
                dueDate=node.product_data.due,
                estimation=node.product_data.awarded,
                deliverable=node.product_data.deliverable,
                thumbnail=node.product_data.thumbnail_upload,
                tags=StringsUpdate(set=node.product_data.tags),
            )
            resp = await self.client.update_products(
                project_id=self.selected_project_id,
                product_ids=[
                    existing_id
                ],  # один продукт – один вызов, чтобы картинка передавалась корректно
                change=change,
            )
            if resp.products_update:
                logging.info(f"{node.name} updated")
        except Exception as e:
            logging.error(f"Failed to update {node.name}: {e}")

    async def check_if_exists(
        self, project_id: str, code: str, parent_id: str | None
    ) -> ExistingItem | None:
        """Checks if a product or group with the given code exists.

        Args:
            code (str): The code of the product or group.
            parent_id (str): The ID of the parent node.

        Returns:
            dict: The existing item's data if found, else None.
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
        logging.info("Окно закрывается, останавливаем event loop...")
        loop = asyncio.get_event_loop()
        loop.stop()  # Останавливаем цикл событий asyncio
        if a0:
            a0.accept()  # Завершаем событие закрытия окна

    def schedule_async(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule an async coroutine to run in the event loop."""
        asyncio.ensure_future(coro)


class PuzzleUploaderApp:
    """Main application class that connects UI and importer."""

    def __init__(self):
        self.app = QApplication(sys.argv)

        # Create event loop
        self.loop = QEventLoop(self.app)
        asyncio.set_event_loop(self.loop)

        # Create UI
        self.ui = PuzzleUploaderUI(self.schedule_async)

        # Create importer
        self.importer = PuzzleImporter(PUZZLE_API, self.ui)

        # Connect UI signals to importer methods
        self.connect_signals()

        # Initialize
        self.schedule_async(self.importer.get_domains())

    def connect_signals(self):
        """Connect UI button clicks to importer methods."""
        self.ui.login_button.clicked.connect(
            lambda: self.schedule_async(self.importer.attempt_login())
        )
        self.ui.csv_button.clicked.connect(self.ui.open_file_dialog)
        self.ui.import_button.clicked.connect(
            lambda: self.schedule_async(self.importer.start_import())
        )

    def schedule_async(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule an async coroutine to run in the event loop."""
        asyncio.ensure_future(coro)

    def run(self):
        """Run the application."""
        self.ui.show()

        with self.loop:
            try:
                self.loop.run_forever()
            except KeyboardInterrupt:
                pass

        return 0


if __name__ == "__main__":
    app = PuzzleUploaderApp()
    sys.exit(app.run())
