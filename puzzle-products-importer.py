#!/usr/bin/env python3

import sys
import os
import csv
import json
import logging
from datetime import datetime
import asyncio  # Added for async support
import mimetypes

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QComboBox, QTextEdit, QCheckBox
)
from PyQt5.QtCore import Qt
from qasync import QEventLoop, asyncSlot

# Import the async PuzzleClient and related classes and methods
from puzzle.client import Client, ProductAdd
from puzzle.enums import ProductKind
from puzzle.base_model import Upload


#PUZZLE_API = "http://l82:8000/api/graphql"
PUZZLE_API = "https://puzzle.mrpost.ru/api/graphql"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')


class ProductTreeNode:
    """Represents a node in the product tree."""

    def __init__(self, name, kind='GROUP', product_data=None):
        """
        Initializes a ProductTreeNode.

        Args:
            name (str): The name of the node.
            kind (str): The kind of node ('GROUP' or 'PRODUCT').
            product_data (dict, optional): The product data if it's a product node.
        """
        self.name = name
        self.kind = kind  # 'GROUP' or 'PRODUCT'
        self.children = {}
        self.product_data = product_data  # Only for 'PRODUCT' nodes


class PuzzleUploaderUI(QWidget):
    """Main application window for the Puzzle Uploader."""

    def __init__(self):
        super().__init__()

        # Set window title
        self.setWindowTitle('Puzzle Uploader')

        # Create layout
        self.layout = QVBoxLayout()
        self.layout.setAlignment(Qt.AlignTop)
        self.setLayout(self.layout)

        # Initialize UI components
        self.init_ui()

        # Initialize variables
        self.csv_file_path = None
        self.selected_project_id = None

        # Initialize the async GraphQL client
        self.client = Client(url=PUZZLE_API)

        # Fetch the list of domains at startup
        self.get_domains()  # Start async call

    def init_ui(self):
        """Initializes the UI components."""
        self.init_login_section()
        self.init_project_section()
        self.init_file_section()
        self.init_import_section()
        self.init_debug_section()

    def init_login_section(self):
        """Initializes the login section of the UI."""
        # Domain selection
        self.domain_label = QLabel('Domain:')
        self.domain_combo = QComboBox()
        self.layout.addWidget(self.domain_label)
        self.layout.addWidget(self.domain_combo)

        # Login input
        self.login_label = QLabel('Login:')
        self.login_input = QLineEdit()
        self.layout.addWidget(self.login_label)
        self.layout.addWidget(self.login_input)

        # Password input
        self.password_label = QLabel('Password:')
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.password_label)
        self.layout.addWidget(self.password_input)

        # Login button
        self.login_button = QPushButton('Login')
        self.login_button.clicked.connect(self.attempt_login)
        self.layout.addWidget(self.login_button)

        # Login status label
        self.login_status_label = QLabel('Please login to continue')
        self.layout.addWidget(self.login_status_label)

    def init_project_section(self):
        """Initializes the project selection section."""
        # Project combo box
        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)
        self.layout.addWidget(self.project_combo)

    def init_file_section(self):
        """Initializes the file selection section."""
        # CSV file selection
        self.csv_button = QPushButton('Select CSV File')
        self.csv_button.clicked.connect(self.open_file_dialog)
        self.layout.addWidget(self.csv_button)

        # CSV file label
        self.csv_label = QLabel('No file selected')
        self.layout.addWidget(self.csv_label)

    def init_import_section(self):
        """Initializes the import section."""
        # Import button
        self.import_button = QPushButton('Start Import')
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.start_import)
        self.layout.addWidget(self.import_button)

        # Import status label
        self.import_status_label = QLabel('')
        self.layout.addWidget(self.import_status_label)

    def init_debug_section(self):
        """Initializes the debug section."""
        # Debug mode checkbox
        self.debug_mode_checkbox = QCheckBox('Debug mode')
        self.debug_mode_checkbox.setChecked(False)
        self.debug_mode_checkbox.stateChanged.connect(self.toggle_debug_mode)
        self.layout.addWidget(self.debug_mode_checkbox)

        # GraphQL request input
        self.graphql_request_label = QLabel('GraphQL Request:')
        self.graphql_request_input = QTextEdit()

        # Send GraphQL request button
        self.send_graphql_button = QPushButton('Send GraphQL Request')
        #self.send_graphql_button.clicked.connect(self.send_graphql_request)

        # GraphQL response output
        self.graphql_response_label = QLabel('GraphQL Response:')
        self.graphql_response_output = QTextEdit()
        self.graphql_response_output.setReadOnly(True)

        # Initially hide debug widgets
        self.set_debug_widgets_visibility(False)

        # Add debug widgets to layout
        self.layout.addWidget(self.graphql_request_label)
        self.layout.addWidget(self.graphql_request_input)
        self.layout.addWidget(self.send_graphql_button)
        self.layout.addWidget(self.graphql_response_label)
        self.layout.addWidget(self.graphql_response_output)

    def set_debug_widgets_visibility(self, visible):
        """Shows or hides debug widgets based on the 'visible' parameter."""
        widgets = [
            self.graphql_request_label,
            self.graphql_request_input,
            self.send_graphql_button,
            self.graphql_response_label,
            self.graphql_response_output
        ]
        for widget in widgets:
            widget.setVisible(visible)

    def toggle_debug_mode(self):
        """Shows or hides debug widgets based on the checkbox state."""
        is_checked = self.debug_mode_checkbox.isChecked()
        self.set_debug_widgets_visibility(is_checked)
        self.adjustSize()

    def open_file_dialog(self):
        """Opens a file dialog to select a CSV file."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if file_path:
            self.csv_label.setText(file_path)
            self.csv_file_path = file_path
            self.import_button.setEnabled(True)
            logging.info(f"CSV file selected: {file_path}")
        else:
            self.csv_label.setText('No file selected')
            self.csv_file_path = None
            self.import_button.setEnabled(False)
            logging.info("No CSV file selected.")

    @asyncSlot()
    async def get_domains(self):
        """Fetches the list of domains via the generated GraphQL client."""
        try:
            response = await self.client.get_domains()
            if response.domains:
                self.domain_combo.clear()
                for domain in response.domains:
                    self.domain_combo.addItem(domain.name, domain.id)
                logging.info("Domain list updated.")
            else:
                logging.error("Failed to fetch domains.")
                self.login_status_label.setText("Error fetching domain list.")
        except Exception as e:
            logging.error(f"Error fetching domains: {e}")
            self.login_status_label.setText(f"Error: {e}")

    @asyncSlot()
    async def attempt_login(self):
        """Attempts to log in using the generated GraphQL client."""
        domain_id = self.domain_combo.currentData()
        username = self.login_input.text().strip()
        password = self.password_input.text()

        if not all([domain_id, username, password]):
            self.login_status_label.setText("Please provide domain, login, and password.")
            logging.warning("Login failed: Missing credentials.")
            return

        self.login_status_label.setText(f"Attempting login to {self.domain_combo.currentText()}...")

        try:
            response = await self.client.login(int(domain_id), username, password)

            if response.login:
                logging.info("Login successful.")
                # The client should manage the session and cookies automatically
                self.login_status_label.setText("Login successful. Fetching projects...")
                self.fetch_projects()
            else:
                logging.error("Login failed.")
                self.login_status_label.setText("Login failed.")
        except Exception as e:
            logging.error(f"Login failed: {e}")
            self.login_status_label.setText(f"Login failed: {e}")

    @asyncSlot()
    async def fetch_projects(self):
        """Fetches the list of projects using the generated GraphQL client."""
        try:
            response = await self.client.get_projects()
            if response.projects:
                active_projects = [p for p in response.projects if p.done_at is None]

                self.project_combo.clear()
                for project in active_projects:
                    self.project_combo.addItem(project.title, project.id)

                if active_projects:
                    self.project_combo.setEnabled(True)
                    self.login_status_label.setText("Projects loaded. Please select a project.")
                    logging.info("Projects loaded successfully.")
                else:
                    self.login_status_label.setText("No active projects available.")
                    logging.info("No active projects found.")
            else:
                self.login_status_label.setText("Failed to fetch projects.")
                logging.error("Failed to fetch projects.")
        except Exception as e:
            logging.error(f"Error fetching projects: {e}")
            self.login_status_label.setText(f"Error: {e}")

    def open_file_dialog(self):
        """Opens a file dialog to select a CSV file."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if file_path:
            self.csv_label.setText(file_path)
            self.csv_file_path = file_path
            self.import_button.setEnabled(True)
            logging.info(f"CSV file selected: {file_path}")
        else:
            self.csv_label.setText('No file selected')
            self.csv_file_path = None
            self.import_button.setEnabled(False)
            logging.info("No CSV file selected.")
    
    @asyncSlot()
    async def start_import(self):
        """Starts the import process when the import button is clicked."""
        if not self.csv_file_path:
            self.import_status_label.setText("Please select a CSV file before importing.")
            logging.warning("Start import failed: No CSV file selected.")
            return

        self.selected_project_id = self.project_combo.currentData()
        if not self.selected_project_id:
            self.import_status_label.setText("Please select a project before importing.")
            logging.warning("Start import failed: No project selected.")
            return

        logging.info(f"Starting import for CSV file: {self.csv_file_path}")
        logging.info(f"Selected project ID: {self.selected_project_id}")
        self.import_status_label.setText("Import started...")

        # Parse CSV file
        root_node = self.parse_csv_file(self.csv_file_path)

        if root_node:
            logging.info("CSV parsed successfully.")
            self.import_status_label.setText("CSV parsed successfully. Starting import...")

            # Generate and execute mutation queries
            await self.generate_mutation_queries(root_node)
            self.import_status_label.setText("Import completed successfully.")
            logging.info("Import completed successfully.")
        else:
            self.import_status_label.setText("Error: Failed to parse the CSV file.")
            logging.error("Import failed: Failed to parse the CSV file.")

    def parse_csv_file(self, file_path):
        """Parses the CSV file and builds a product tree.

        Args:
            file_path (str): The path to the CSV file.

        Returns:
            ProductTreeNode: The root node of the product tree.
        """
        root = ProductTreeNode("root")
        try:
            logging.info(f"Parsing CSV file: {file_path}")
            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                for row in reader:
                    path = row.get('path', '')
                    product_code = row.get('code', '')
                    if not product_code:
                        logging.warning("Skipping row with missing product code.")
                        continue

                    # Build the path in the tree
                    path_parts = path.split('/')
                    current_node = root

                    for part in path_parts:
                        if part not in current_node.children:
                            current_node.children[part] = ProductTreeNode(part)
                        current_node = current_node.children[part]

                    # Add the product node
                    if product_code not in current_node.children:
                        current_node.children[product_code] = ProductTreeNode(
                            product_code, kind='PRODUCT', product_data=row
                        )
                    else:
                        logging.warning(f"Duplicate product code '{product_code}' in CSV. Skipping duplicate.")
            logging.info("CSV parsing completed.")
            return root

        except Exception as e:
            logging.error(f"Error parsing CSV file: {e}")
            self.import_status_label.setText(f"Error parsing CSV: {e}")
            return None

    async def generate_mutation_queries(self, root, parent_id=None):
        """Recursively generates and executes mutation queries.

        Args:
            root (ProductTreeNode): The root node of the product tree.
            parent_id (str, optional): The ID of the parent node in the API.
        """
        for child_name, child_node in root.children.items():
            self.import_status_label.setText(f"Importing {child_node.kind.lower()} '{child_name}'...")

            existing_item = await self.check_if_exists(child_name, parent_id)

            if existing_item:
                if existing_item['kind'] != child_node.kind:
                    logging.warning(f"Conflict: '{child_name}' is a {existing_item['kind']} but expected {child_node.kind}.")
                    continue
                else:
                    logging.info(f"{child_name} already exists as {child_node.kind}. Skipping creation.")
                    if child_node.kind == 'GROUP':
                        await self.generate_mutation_queries(child_node, existing_item['id'])
                    continue

            if child_node.kind == 'GROUP':
                # Create product group
                new_parent_id = await self.create_product_group(child_node, parent_id)
                if new_parent_id:
                    await self.generate_mutation_queries(child_node, parent_id=new_parent_id)
            elif child_node.kind == 'PRODUCT':
                # Create product
                await self.create_product(child_node, parent_id)
    
    ####

    async def create_product_group(self, node, parent_id):
        """Creates a product group via GraphQL mutation.

        Args:
            node (ProductTreeNode): The node representing the product group.
            parent_id (str): The ID of the parent node.

        Returns:
            str: The ID of the newly created group, or None if creation failed.
        """
        product_input = {
            'projectId': self.selected_project_id,
            'parentId': parent_id,
            'code': node.name,
            'kind': 'GROUP',
            'description': {'ops': []},
            'tags': []
        }

        try:
            response = await self.client.create_product_group(product_input)
            if response.product_create and response.product_create.id:
                group_id = response.product_create.id
                logging.info(f"Group '{node.name}' created successfully with ID {group_id}.")
                return group_id
            else:
                logging.warning(f"Failed to create group '{node.name}'.")
                return None
        except Exception as e:
            logging.error(f"Error creating group '{node.name}': {e}")
            return None

    async def create_product(self, node, parent_id):
        """Creates a product via GraphQL mutation.

        Args:
            node (ProductTreeNode): The node representing the product.
            parent_id (str): The ID of the parent node.
        """
        product_data = node.product_data

        # Extract and format product data with proper checks and defaults

        # Handle 'deliverable' field
        deliverable_str = str(product_data.get('deliverable', '')).strip().lower()
        if deliverable_str == '':
            deliverable_value = False
        else:
            deliverable_value = deliverable_str == 'true'

        # Handle 'awarded' field (estimation)
        awarded_str = str(product_data.get('awarded', '')).strip()
        if awarded_str == '':
            estimation_value = 0
        else:
            try:
                estimation_value = int(awarded_str)
            except (ValueError, TypeError):
                logging.warning(f"Invalid estimation value '{awarded_str}' for product '{node.name}'. Using default '0'.")
                estimation_value = 0

        # Handle 'due' field (due date)
        due_str = str(product_data.get('due', '')).strip()
        due_value = self.parse_due_date(due_str)

        # Handle 'status' field
        status_str = str(product_data.get('status', '')).strip().upper()
        if status_str == '':
            status_value = 'ACTIVE'
        elif status_str in ['ACTIVE', 'COMPLETED', 'CANCELED']:
            status_value = status_str
        else:
            logging.warning(f"Invalid status '{status_str}' for product '{node.name}'. Using default 'ACTIVE'.")
            status_value = 'ACTIVE'

        # Handle 'tags' field
        tags_str = product_data.get('tags', '')
        if isinstance(tags_str, str):
            tags_list = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        else:
            logging.warning(f"Invalid tags '{tags_str}' for product '{node.name}'. Using empty list.")
            tags_list = []

        # Handle 'description' field
        description_str = product_data.get('description', '')
        if description_str:
            try:
                description = json.loads(description_str)
            except json.JSONDecodeError:
                logging.warning(f"Invalid description for product '{node.name}'. Using empty description.")
                description = {"ops": []}
        else:
            description = {"ops": []}

        # Handle thumbnail (file upload)
        picture_field = product_data.get('picture', '').strip()
        image_path = None
        if picture_field:
            image_path = os.path.join(os.path.dirname(self.csv_file_path), picture_field)
            if os.path.exists(image_path):
                logging.info(f"Including thumbnail for product '{node.name}'.")
                mime_type, _ = mimetypes.guess_type(image_path)
                thumbnail_upload = Upload(
                    filename=os.path.basename(image_path),
                    content=open(image_path, "rb"),
                    content_type=mime_type,
                )
            else:
                logging.warning(f"Image file '{image_path}' not found. Proceeding without thumbnail.")
                thumbnail_upload = None
        else:
            logging.info(f"No thumbnail for product '{node.name}'.")
            thumbnail_upload = None

        # Prepare product input data
        product_add = ProductAdd(
            projectId=self.selected_project_id,
            parentId=parent_id,
            status=status_value,
            due_to=due_value,
            estimation=estimation_value,
            deliverable=deliverable_value,
            code=node.name,
            kind=ProductKind.PRODUCT,
            description=description,
            thumbnail=thumbnail_upload,
            tags=tags_list
        )

        # Now try to create the product
        try:
            response = await self.client.create_product(product_add)
            if response.product_create and response.product_create.id:
                product_id = response.product_create.id
                logging.info(f"Product '{node.name}' created successfully with ID {product_id}.")
            else:
                logging.warning(f"Failed to create product '{node.name}'.")
        except Exception as e:
            logging.error(f"Error creating product '{node.name}': {e}")

    @staticmethod
    def parse_due_date(due_str):
        """Parses the due date string to ISO format.

        Args:
            due_str (str): The due date string in 'DD.MM.YYYY' format.

        Returns:
            str: The ISO formatted date string, or None if invalid.
        """
        try:
            due_date_obj = datetime.strptime(due_str, '%d.%m.%y')
            return due_date_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            logging.warning(f"Invalid date format for due date '{due_str}'.")
            return None
  
    async def check_if_exists(self, code, parent_id):
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
            response = await self.client.get_product_descendants(self.selected_project_id, parent_ids, 1)
            if response.product_descendants:
                for descendant in response.product_descendants:
                    if descendant.code == code:
                        logging.info(f"Found existing {descendant.kind} with code '{code}'.")
                        return {
                            'kind': descendant.kind,
                            'id': descendant.id,
                            'code': descendant.code,
                            'parentId': descendant.parent_id
                        }
            else:
                logging.info(f"No existing item found for code '{code}'.")
            return None
        except Exception as e:
            logging.error(f"Error checking existence of '{code}': {e}")
            return None

    # Переопределяем обработчик закрытия окна
    def closeEvent(self, event):
        logging.info("Окно закрывается, останавливаем event loop...")
        loop = asyncio.get_event_loop()
        loop.stop()  # Останавливаем цикл событий asyncio
        event.accept()  # Завершаем событие закрытия окна

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Создаем Qt-совместимый event loop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = PuzzleUploaderUI()
    window.show()

    # Запускаем цикл событий asyncio вместе с PyQt
    with loop:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass  # Для завершения через Ctrl+C, если требуется

    sys.exit(0)
