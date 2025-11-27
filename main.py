#!/usr/bin/env python3

# Main module for the Puzzle products importer application
# Integrates UI and API logic to upload data from CSV files

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

# Import the async Puzzle client and related classes
from puzzle.client import Client, ProductAdd, ProductChange
from puzzle.enums import ProductKind
from puzzle.exceptions import GraphQLClientGraphQLError, GraphQLClientHttpError
from puzzle.input_types import StringsUpdate

# Import local modules
from ui_layout import PuzzleUploaderUI
from csv_handler import ProductNode, ProductGroupNode, parse_csv_file


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")


# TypedDict describing an existing item in the system
class ExistingItem(TypedDict):
    kind: str
    id: str
    code: str
    parentId: str | None


class PuzzleImporter:
    """Handles interactions with the Puzzle API to import products.

    Responsibilities include:
    - Authenticating to Puzzle
    - Fetching available domains and projects
    - Importing products from CSV files
    - Updating existing products
    - Creating groups and products using GraphQL
    """

    def __init__(self, api_url: str, ui: PuzzleUploaderUI):
        self.client = Client(url=api_url)
        self.ui = ui
        self.selected_project_id: str | None = None
        self.csv_file_path: str | None = None
        self.update_mode = False

    @asyncSlot()
    async def get_domains(self):
        """Fetch the list of domains using the GraphQL client."""
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
        """Attempt to log in using the GraphQL client."""
        domain_name = self.ui.domain_combo.currentData()
        username = self.ui.login_input.text().strip()
        password = self.ui.password_input.text()

        # Verify required credentials are present
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
                # The client manages session and cookies automatically
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
        """Fetch the list of projects using the GraphQL client."""
        try:
            response = await self.client.get_projects()
            if response.projects:
                # Filter only active (not completed) projects
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
        """Start the import process when the import button is pressed."""
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

        # Save the update mode setting
        self.update_mode = self.ui.update_mode_checkbox.isChecked()

        # Parse the CSV file
        root_node = parse_csv_file(self.csv_file_path)

        if root_node:
            logging.info("CSV parsed successfully.")
            self.ui.import_status_label.setText(
                "CSV parsed successfully. Starting import..."
            )

            # Generate and execute GraphQL mutation queries
            await self.generate_mutation_queries(root_node)
            self.ui.import_status_label.setText("Import completed successfully.")
            logging.info("Import completed successfully.")
        else:
            self.ui.import_status_label.setText("Error: Failed to parse the CSV file.")
            logging.error("Import failed: Failed to parse the CSV file.")

    async def generate_mutation_queries(
        self, root: ProductGroupNode, parent_id: str | None = None
    ):
        """Recursively generate and execute GraphQL mutation queries.

        Args:
            root (ProductGroupNode): Root node of the product tree.
            parent_id (str, optional): ID of the parent item in the API.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for import.")
            return

        for child_name, child_node in root.children.items():
            self.ui.import_status_label.setText(f"Importing '{child_name}'...")
            logging.info(f"Processing '{child_name}'...")
            logging.debug(f"Child node details: {child_node}")

            # Check if an item with this name already exists
            existing_item = await self.check_if_exists(
                self.selected_project_id, child_name, parent_id
            )

            if existing_item:
                # Determine the expected item kind
                child_kind = (
                    ProductKind.GROUP
                    if isinstance(child_node, ProductGroupNode)
                    else ProductKind.PRODUCT
                )
                # Validate the kind of existing item
                if existing_item["kind"] != child_kind:
                    logging.warning(
                        f"Conflict: '{child_name}' is a {existing_item['kind']} but expected {child_kind}."
                    )
                    continue
                # When update mode is enabled, update the product
                if self.update_mode and isinstance(child_node, ProductNode):
                    await self.update_product(child_node, existing_item["id"])
                    continue
                else:
                    logging.info(
                        f"{child_name} already exists as {child_kind}. Skipping creation."
                    )
                    # For groups, process child nodes recursively
                    if isinstance(child_node, ProductGroupNode):
                        await self.generate_mutation_queries(
                            child_node, existing_item["id"]
                        )
                    continue

            if isinstance(child_node, ProductGroupNode):
                # Create a product group
                new_parent_id = await self.create_product_group(child_node, parent_id)
                if new_parent_id:
                    await self.generate_mutation_queries(
                        child_node, parent_id=new_parent_id
                    )
            else:
                # Create a product
                await self.create_product(child_node, parent_id)

    ####

    async def create_product_group(self, node: ProductGroupNode, parent_id: str | None):
        """Create a product group via a GraphQL mutation.

        Args:
            node (ProductGroupNode): Node representing the group.
            parent_id (str): ID of the parent node.

        Returns:
            str: ID of the created group, or None if creation failed.
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
        """Create a product via a GraphQL mutation.

        Args:
            node (ProductNode): Node representing the product.
            parent_id (str): ID of the parent node.
        """
        if self.selected_project_id is None:
            logging.error("No project selected for creating product.")
            return

        if self.csv_file_path is None:
            logging.warning("No csv file selected, skipping")
            return

        # Prepare product input for creation
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

        # Try to create the product
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
        """Update an existing product using a GraphQL mutation.

        Args:
            node (ProductNode): Node containing updated product data.
            existing_id (str): ID of the existing product.
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
            # Prepare the changes for update
            change = ProductChange(
                status=node.product_data.status,
                dueDate=node.product_data.due,
                estimation=node.product_data.awarded,
                deliverable=node.product_data.deliverable,
                thumbnail=node.product_data.thumbnail_upload,
                tags=StringsUpdate(set=node.product_data.tags),
            )
            # Update the product (single product update to handle file uploads correctly)
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
        """Check whether a product or group with the given code exists.

        Args:
            code (str): Code of the product or group.
            parent_id (str): ID of the parent node.

        Returns:
            dict: Details of the existing item if found; otherwise None.
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

    # Override close event handler
    def closeEvent(self, a0: QtGui.QCloseEvent | None) -> None:
        """Handle the application window close event."""
        logging.info("Window is closing, stopping the event loop...")
        loop = asyncio.get_event_loop()
        loop.stop()  # Stop the asyncio event loop
        if a0:
            a0.accept()  # Accept the close event

    def schedule_async(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule an async coroutine to run on the event loop."""
        asyncio.ensure_future(coro)


class PuzzleUploaderApp:
    """Top-level application class, bridging UI and the importer."""

    def __init__(self):
        self.app = QApplication(sys.argv)

        # Create the event loop
        self.loop = QEventLoop(self.app)
        asyncio.set_event_loop(self.loop)

        # Create the UI
        self.ui = PuzzleUploaderUI(self.schedule_async)

        # Puzzle API URL (can be switched to local or production servers)
        puzzle_api = "https://puzzle.mrpost.ru/api/graphql"

        if os.environ.get("PUZZLE_API"):
            puzzle_api = os.environ["PUZZLE_API"]

        # Create the importer
        self.importer = PuzzleImporter(puzzle_api, self.ui)

        # Connect UI signals to importer methods
        self.connect_signals()

        # Initialization: load domain list
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
        """Schedule async coroutine execution on the event loop."""
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
    dotenv.load_dotenv()
    if os.environ.get("LOG_LEVEL"):
        log_level = os.environ["LOG_LEVEL"].upper()
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))
    app = PuzzleUploaderApp()
    sys.exit(app.run())
