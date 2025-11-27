"""CSV file processing and product tree structure.

This module is responsible for:
- Parsing CSV files with product data
- Validating data with Pydantic
- Building a tree of product groups and products
- Handling images and product metadata
"""

import csv
from datetime import datetime
import logging
import mimetypes
import os
from pydantic import BaseModel, ValidationError

from puzzle.base_model import Upload
from puzzle.enums import ProductStatusEnum


# Example CSV format:
# path,code,awarded,due,picture,deliverable,status,tags
# episode01/seq01,0010,10,21.06.2025,images/0010.png,TRUE,ACTIVE,tag1 tag2
# episode01/seq01,0020,,,,,,


class CsvRow(BaseModel):
    """Model for validating a single CSV row."""

    path: str
    code: str
    awarded: str
    due: str
    picture: str
    deliverable: str
    status: str
    tags: str


class ParsedRow:
    """Represents a parsed CSV row with validated and converted data."""

    def __init__(self, csv_row: CsvRow, csv_file_path: str):
        self.path = csv_row.path
        self.code = csv_row.code
        # Convert awarded to an integer
        self.awarded = int(csv_row.awarded) if csv_row.awarded else 0
        # Parse due date
        self.due = self.parse_due_date(csv_row.due)
        # Convert the 'deliverable' flag to a boolean
        self.deliverable = csv_row.deliverable == "TRUE"
        # Convert the string status to the enum
        status_str = csv_row.status.strip().upper()
        if status_str == "" or status_str == "ACTIVE":
            self.status = ProductStatusEnum.ACTIVE
        elif status_str == "COMPLETED":
            self.status = ProductStatusEnum.COMPLETED
        elif status_str == "CANCELED":
            self.status = ProductStatusEnum.CANCELED
        else:
            self.status = ProductStatusEnum.ACTIVE
        # Parse tags from space-separated string
        self.tags = [tag.strip() for tag in csv_row.tags.split(" ") if tag.strip()]

        # Process thumbnail (upload image file if exists)
        picture_field = csv_row.picture.strip()
        image_path = None
        if picture_field:
            # Construct the full path to the image relative to the CSV file
            image_path = os.path.join(os.path.dirname(csv_file_path), picture_field)
            if os.path.exists(image_path):
                logging.info(
                    f"Including thumbnail for product '{csv_row.path}/{csv_row.code}'."
                )
                mime_type, _ = mimetypes.guess_type(image_path)
                thumbnail_upload = (
                    Upload(
                        filename=os.path.basename(image_path),
                        content=open(image_path, "rb"),
                        content_type=mime_type,
                    )
                    if mime_type
                    else None
                )
            else:
                logging.warning(
                    f"Image file '{image_path}' not found. Proceeding without thumbnail."
                )
                thumbnail_upload = None
        else:
            logging.info(f"No thumbnail for product '{csv_row.path}/{csv_row.code}'.")
            thumbnail_upload = None
        self.thumbnail_upload = thumbnail_upload

        # # Description field processing (commented out)
        # description_str = product_data.description
        # if description_str:
        #     try:
        #         description = json.loads(description_str)
        #     except json.JSONDecodeError:
        #         logging.warning(
        #             f"Invalid description for product '{node.name}'. Using empty description."
        #         )
        #         description = {"ops": []}
        # else:
        #     description = {"ops": []}

    @staticmethod
    def parse_due_date(due_str: str):
        """Parse a due date string and return an ISO timestamp.

        Args:
            due_str (str): Date string in 'DD.MM.YYYY' or 'DD.MM.YY' formats.

        Returns:
            str: ISO formatted timestamp string, or None for empty/invalid input.
        """
        # Try parsing with four-digit year first, then with two-digit year
        for fmt in ("%d.%m.%Y", "%d.%m.%y"):
            try:
                due_date_obj = datetime.strptime(due_str, fmt)
                # Normalize to zero-time Zulu format
                return due_date_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
        if due_str.strip() == "":
            # Empty due date is not an error; return None silently
            return None
        logging.warning(f"Invalid date format for due date '{due_str}'.")
        return None


class ProductGroupNode:
    """Represents a group node in the product tree.

    A group organizes products into a hierarchical structure and may contain
    product nodes and/or other groups.
    """

    def __init__(self, csv_file_path: str, name: str):
        """Initialize a product group node.

        Args:
            csv_file_path (str): Path to the CSV file.
            name (str): Name of the group.
        """
        self.name = name
        self.children: dict[str, ProductNode | ProductGroupNode] = {}


class ProductNode:
    """Represents a product node in the tree.

    Holds product data along with metadata and attached files.
    """

    def __init__(
        self,
        csv_file_path: str,
        name: str,
        product_data: CsvRow,
    ):
        """Initialize a product node.

        Args:
            csv_file_path (str): Path to the CSV file.
            name (str): Product code/name.
            product_data (CsvRow): Product data parsed from the CSV.
        """
        self.name = name
        self.product_data = ParsedRow(product_data, csv_file_path)


def parse_csv_file(file_path: str) -> ProductGroupNode | None:
    """Parse a CSV file and build the product tree.

    Args:
        file_path (str): Path to the CSV file.

    Returns:
        ProductGroupNode: Root node of the product tree, or None if parsing failed.
    """
    root = ProductGroupNode(file_path, "root")
    try:
        logging.info(f"Parsing CSV file: {file_path}")
        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                try:
                    # Validate and parse the row using pydantic
                    csvRow = CsvRow(**row)  # pyright: ignore[reportArgumentType]

                    product_code = csvRow.code
                    if not product_code:
                        logging.warning("Skipping row with missing product code.")
                        continue

                    # Build a path in the product tree
                    path_parts = csvRow.path.split("/")
                    current_parent_node = root

                    # Traverse each path segment creating groups as needed
                    for part in path_parts:
                        if part not in current_parent_node.children:
                            next_parent = ProductGroupNode(file_path, part)
                            current_parent_node.children[part] = next_parent
                            current_parent_node = next_parent
                        else:
                            current_parent_node = current_parent_node.children[part]

                    # Add the product node at the final path node
                    if product_code not in current_parent_node.children:
                        current_parent_node.children[product_code] = ProductNode(
                            file_path,
                            product_code,
                            product_data=csvRow,
                        )
                    else:
                        logging.warning(
                            f"Duplicate product code '{product_code}' in CSV. Skipping duplicate."
                        )
                except ValidationError as e:
                    logging.warning(f"Skipping row due to validation error: {e}")
                    continue

        logging.info("CSV parsing completed.")
        return root

    except Exception as e:
        logging.error(f"Error parsing CSV file: {e}")
        return None
