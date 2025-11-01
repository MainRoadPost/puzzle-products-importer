"""CSV file handling and product tree structure."""

import csv
from datetime import datetime
import logging
import mimetypes
import os
from pydantic import BaseModel, ValidationError

from puzzle.base_model import Upload
from puzzle.enums import ProductKind, ProductStatusEnum


# CSV example
# path,code,awarded,due,picture,deliverable,status,tags
# episode01/seq01,0010,10,21.06.2025,images/0010.png,TRUE,ACTIVE,tag1 tag2
# episode01/seq01,0020,,,,,,


class CsvRow(BaseModel):
    path: str
    code: str
    awarded: str
    due: str
    picture: str
    deliverable: str
    status: str
    tags: str


class ParsedRow:
    """Represents a parsed row from the CSV file."""

    def __init__(self, csv_row: CsvRow, csv_file_path: str):
        self.path = csv_row.path
        self.code = csv_row.code
        self.awarded = int(csv_row.awarded) if csv_row.awarded else 0
        self.due = self.parse_due_date(csv_row.due)
        self.deliverable = csv_row.deliverable == "TRUE"
        status_str = csv_row.status.strip().upper()
        if status_str == "" or status_str == "ACTIVE":
            self.status = ProductStatusEnum.ACTIVE
        elif status_str == "COMPLETED":
            self.status = ProductStatusEnum.COMPLETED
        elif status_str == "CANCELED":
            self.status = ProductStatusEnum.CANCELED
        else:
            self.status = ProductStatusEnum.ACTIVE
        self.tags = [tag.strip() for tag in csv_row.tags.split(" ") if tag.strip()]

        # Handle thumbnail (file upload)
        picture_field = csv_row.picture.strip()
        image_path = None
        if picture_field:
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

        # # Handle 'description' field
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
        """Parses the due date string to ISO format.

        Args:
            due_str (str): The due date string in 'DD.MM.YYYY' format.

        Returns:
            str: The ISO formatted date string, or None if invalid.
        """
        try:
            due_date_obj = datetime.strptime(due_str, "%d.%m.%y")
            return due_date_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            logging.warning(f"Invalid date format for due date '{due_str}'.")
            return None


class ProductGroupNode:
    """Represents a group node in the product tree."""

    def __init__(self, csv_file_path: str, name: str):
        """
        Initializes a ProductGroupNode.

        Args:
            name (str): The name of the group node.
        """
        self.name = name
        self.kind = ProductKind.GROUP  # 'GROUP' node
        self.children: dict[str, ProductNode | ProductGroupNode] = {}


class ProductNode:
    """Represents a node in the product tree."""

    def __init__(
        self,
        csv_file_path: str,
        name: str,
        product_data: CsvRow,
    ):
        """
        Initializes a ProductTreeNode.

        Args:
            name (str): The name of the node.
            kind (str): The kind of node ('GROUP' or 'PRODUCT').
            product_data (dict, optional): The product data if it's a product node.
        """
        self.name = name
        self.product_data = ParsedRow(product_data, csv_file_path)


def parse_csv_file(file_path: str) -> ProductGroupNode | None:
    """Parses the CSV file and builds a product tree.

    Args:
        file_path (str): The path to the CSV file.

    Returns:
        ProductGroupNode: The root node of the product tree, or None if parsing fails.
    """
    root = ProductGroupNode(file_path, "root")
    try:
        logging.info(f"Parsing CSV file: {file_path}")
        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                try:
                    # validate and parse row using pydantic
                    csvRow = CsvRow(**row)  # pyright: ignore[reportArgumentType]

                    product_code = csvRow.code
                    if not product_code:
                        logging.warning("Skipping row with missing product code.")
                        continue

                    # Build the path in the tree
                    path_parts = csvRow.path.split("/")
                    current_parent_node = root

                    for part in path_parts:
                        if part not in current_parent_node.children:
                            next_parent = ProductGroupNode(file_path, part)
                            current_parent_node.children[part] = next_parent
                            current_parent_node = next_parent

                    # Add the product node
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
