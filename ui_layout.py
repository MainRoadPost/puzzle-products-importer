"""UI layout and components for the Puzzle Uploader application.

This module defines a PyQt5 based user interface including:
- Login form
- Project selection
- CSV import controls
- Import process monitor
- Debugging mode for GraphQL requests
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
    """Main window for the Puzzle Uploader application.

    Provides a GUI for:
    - Logging into Puzzle
    - Selecting a project
    - Uploading CSV files of products
    - Starting the import process
    - Debugging GraphQL requests
    """

    def __init__(
        self, schedule_async_callback: Callable[[Coroutine[Any, Any, None]], None]
    ):
        """
        Initialize the UI.

        Args:
            schedule_async_callback: Callback function used to schedule async coroutines
        """
        super().__init__()

        self.schedule_async = schedule_async_callback

        # Set the window title
        self.setWindowTitle("Puzzle Uploader")

        # Create layout
        self.ui_layout = QVBoxLayout()
        self.ui_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(self.ui_layout)

        # Initialize UI components
        self.init_ui()

        # Initialize variables
        self.csv_file_path: str | None = None

    def init_ui(self):
        """Initialize UI components."""
        self.init_login_section()
        self.init_project_section()
        self.init_file_section()
        self.init_import_section()
        self.init_debug_section()

    def init_login_section(self):
        """Initialize the login section of the UI."""
        # Domain selection
        self.domain_label = QLabel("Domain:")
        self.domain_combo = QComboBox()
        self.ui_layout.addWidget(self.domain_label)
        self.ui_layout.addWidget(self.domain_combo)

        # Login input field
        self.login_label = QLabel("Login:")
        self.login_input = QLineEdit()
        self.ui_layout.addWidget(self.login_label)
        self.ui_layout.addWidget(self.login_input)

        # Password input field
        self.password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ui_layout.addWidget(self.password_label)
        self.ui_layout.addWidget(self.password_input)

        # Login button
        self.login_button = QPushButton("Login")
        self.ui_layout.addWidget(self.login_button)

        # Login status label
        self.login_status_label = QLabel("Please login to continue")
        self.ui_layout.addWidget(self.login_status_label)

    def init_project_section(self):
        """Initialize the project selection section."""
        # Project selection combo box
        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)
        self.ui_layout.addWidget(self.project_combo)

    def init_file_section(self):
        """Initialize the file selection section."""
        # CSV selection button
        self.csv_button = QPushButton("Select CSV File")
        self.ui_layout.addWidget(self.csv_button)

        # Label showing path to the selected file
        self.csv_label = QLabel("No file selected")
        self.ui_layout.addWidget(self.csv_label)

    def init_import_section(self):
        """Initialize the import control section."""

        # Import start button
        self.import_button = QPushButton("Start Import")
        self.import_button.setEnabled(False)
        self.ui_layout.addWidget(self.import_button)

        # Checkbox for update mode
        self.update_mode_checkbox = QCheckBox("Update")
        self.update_mode_checkbox.setChecked(False)  # Disabled by default
        self.ui_layout.addWidget(self.update_mode_checkbox)

        # Import status label
        self.import_status_label = QLabel("")
        self.ui_layout.addWidget(self.import_status_label)

    def init_debug_section(self):
        """Initialize the debug controls section."""
        # Debug mode checkbox
        self.debug_mode_checkbox = QCheckBox("Debug mode")
        self.debug_mode_checkbox.setChecked(False)
        self.debug_mode_checkbox.stateChanged.connect(self.toggle_debug_mode)
        self.ui_layout.addWidget(self.debug_mode_checkbox)

        # Dry-run checkbox
        self.dry_run_checkbox = QCheckBox("Dry run")
        self.dry_run_checkbox.setChecked(False)
        self.ui_layout.addWidget(self.dry_run_checkbox)

        # GraphQL request input
        self.graphql_request_label = QLabel("GraphQL Request:")
        self.graphql_request_input = QTextEdit()

        # Send GraphQL request button
        self.send_graphql_button = QPushButton("Send GraphQL Request")
        # self.send_graphql_button.clicked.connect(self.send_graphql_request)

        # GraphQL response output
        self.graphql_response_label = QLabel("GraphQL Response:")
        self.graphql_response_output = QTextEdit()
        self.graphql_response_output.setReadOnly(True)

        # Initially hide debug widgets
        self.set_debug_widgets_visibility(False)

        # Add debug widgets to layout
        self.ui_layout.addWidget(self.graphql_request_label)
        self.ui_layout.addWidget(self.graphql_request_input)
        self.ui_layout.addWidget(self.send_graphql_button)
        self.ui_layout.addWidget(self.graphql_response_label)
        self.ui_layout.addWidget(self.graphql_response_output)

    def set_debug_widgets_visibility(self, visible: bool):
        """Show or hide debug widgets based on the 'visible' flag."""
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
        """Toggle the visibility of debug widgets based on the checkbox state."""
        is_checked = self.debug_mode_checkbox.isChecked()
        self.set_debug_widgets_visibility(is_checked)
        self.adjustSize()

    def open_file_dialog(self):
        """Open a file dialog to select a CSV file."""
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
