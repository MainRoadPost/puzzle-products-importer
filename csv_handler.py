"""Обработка CSV файлов и структура дерева продуктов.

Модуль отвечает за:
- Парсинг CSV файлов с данными продуктов
- Валидацию данных с помощью Pydantic
- Построение древовидной структуры продуктов и групп
- Обработку изображений и метаданных продуктов
"""

import csv
from datetime import datetime
import logging
import mimetypes
import os
from pydantic import BaseModel, ValidationError

from puzzle.base_model import Upload
from puzzle.enums import ProductStatusEnum


# Пример формата CSV файла:
# path,code,awarded,due,picture,deliverable,status,tags
# episode01/seq01,0010,10,21.06.2025,images/0010.png,TRUE,ACTIVE,tag1 tag2
# episode01/seq01,0020,,,,,,


class CsvRow(BaseModel):
    """Модель для валидации строки CSV файла."""

    path: str
    code: str
    awarded: str
    due: str
    picture: str
    deliverable: str
    status: str
    tags: str


class ParsedRow:
    """Представляет распарсенную строку из CSV файла с валидированными и преобразованными данными."""

    def __init__(self, csv_row: CsvRow, csv_file_path: str):
        self.path = csv_row.path
        self.code = csv_row.code
        # Преобразуем awarded в число
        self.awarded = int(csv_row.awarded) if csv_row.awarded else 0
        # Парсим дату окончания
        self.due = self.parse_due_date(csv_row.due)
        # Преобразуем флаг deliverable в булево значение
        self.deliverable = csv_row.deliverable == "TRUE"
        # Преобразуем строковый статус в enum
        status_str = csv_row.status.strip().upper()
        if status_str == "" or status_str == "ACTIVE":
            self.status = ProductStatusEnum.ACTIVE
        elif status_str == "COMPLETED":
            self.status = ProductStatusEnum.COMPLETED
        elif status_str == "CANCELED":
            self.status = ProductStatusEnum.CANCELED
        else:
            self.status = ProductStatusEnum.ACTIVE
        # Парсим теги из строки с разделителем-пробелом
        self.tags = [tag.strip() for tag in csv_row.tags.split(" ") if tag.strip()]

        # Обрабатываем thumbnail (загрузка файла изображения)
        picture_field = csv_row.picture.strip()
        image_path = None
        if picture_field:
            # Формируем полный путь к изображению относительно CSV файла
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

        # # Обработка поля 'description' (закомментировано)
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
        """Парсит строку даты окончания в формат ISO.

        Args:
            due_str (str): Строка даты в формате 'DD.MM.YY'.

        Returns:
            str: Дата в ISO формате, или None если формат неверный.
        """
        try:
            due_date_obj = datetime.strptime(due_str, "%d.%m.%y")
            return due_date_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            logging.warning(f"Invalid date format for due date '{due_str}'.")
            return None


class ProductGroupNode:
    """Представляет узел группы в дереве продуктов.

    Группа используется для организации продуктов в иерархическую структуру.
    Может содержать как продукты, так и другие группы.
    """

    def __init__(self, csv_file_path: str, name: str):
        """
        Инициализирует узел группы продуктов.

        Args:
            csv_file_path (str): Путь к CSV файлу.
            name (str): Название группы.
        """
        self.name = name
        self.children: dict[str, ProductNode | ProductGroupNode] = {}


class ProductNode:
    """Представляет узел продукта в дереве.

    Содержит все данные о продукте, включая метаданные и файлы.
    """

    def __init__(
        self,
        csv_file_path: str,
        name: str,
        product_data: CsvRow,
    ):
        """
        Инициализирует узел продукта.

        Args:
            csv_file_path (str): Путь к CSV файлу.
            name (str): Название продукта.
            product_data (CsvRow): Данные продукта из CSV.
        """
        self.name = name
        self.product_data = ParsedRow(product_data, csv_file_path)


def parse_csv_file(file_path: str) -> ProductGroupNode | None:
    """Парсит CSV файл и строит дерево продуктов.

    Args:
        file_path (str): Путь к CSV файлу.

    Returns:
        ProductGroupNode: Корневой узел дерева продуктов, или None если парсинг не удался.
    """
    root = ProductGroupNode(file_path, "root")
    try:
        logging.info(f"Parsing CSV file: {file_path}")
        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                try:
                    # Валидируем и парсим строку с помощью pydantic
                    csvRow = CsvRow(**row)  # pyright: ignore[reportArgumentType]

                    product_code = csvRow.code
                    if not product_code:
                        logging.warning("Skipping row with missing product code.")
                        continue

                    # Строим путь в дереве продуктов
                    path_parts = csvRow.path.split("/")
                    current_parent_node = root

                    # Проходим по каждой части пути, создавая группы при необходимости
                    for part in path_parts:
                        if part not in current_parent_node.children:
                            next_parent = ProductGroupNode(file_path, part)
                            current_parent_node.children[part] = next_parent
                            current_parent_node = next_parent

                    # Добавляем узел продукта в конец пути
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
