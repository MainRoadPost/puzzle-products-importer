import os
import tempfile
import unittest

from csv_handler import ProductGroupNode


class TestCSVHandler(unittest.TestCase):
    def test_parse_csv_create_tree(self):
        csv_content = (
            "path,code,awarded,due,picture,deliverable,status,tags\n"
            "episode01/seq01,0010,10,21.06.2025,images/0010.png,TRUE,ACTIVE,tag1 tag2\n"
            "episode01/seq01,0020,,,,,,\n"
            "episode01/seq02,0030,5,22.06.2025,images/0030.png,FALSE,ACTIVE,tag3\n"
        )

        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as tmp:
            tmp.write(csv_content)
            tmp_path = tmp.name

        try:
            # Import here to avoid linter warnings when pydantic is absent
            from csv_handler import parse_csv_file

            root = parse_csv_file(tmp_path)
            if root is None:
                self.fail("parse_csv_file returned None")
            # Verify groups and products
            self.assertIn("episode01", root.children)
            episode_group = root.children["episode01"]
            if not isinstance(episode_group, ProductGroupNode):
                self.fail("episode01 group is not a group")
            self.assertIn("seq01", episode_group.children)
            seq01 = episode_group.children["seq01"]
            if not isinstance(seq01, ProductGroupNode):
                self.fail("seq01 group is not a group")
            self.assertIn("0010", seq01.children)
            self.assertIn("0020", seq01.children)
            self.assertIn("seq02", episode_group.children)
            if not isinstance(episode_group.children["seq02"], ProductGroupNode):
                self.fail("seq02 group is not a group")
            self.assertIn("0030", episode_group.children["seq02"].children)
        finally:
            os.remove(tmp_path)

    def test_parse_due_date_formats(self):
        # Import inside test to avoid missing dependency errors when skipped
        from csv_handler import ParsedRow

        # 4-digit year
        self.assertEqual(ParsedRow.parse_due_date("21.06.2025"), "2025-06-21T00:00:00Z")
        # 2-digit year
        self.assertEqual(ParsedRow.parse_due_date("21.06.25"), "2025-06-21T00:00:00Z")
        # Empty string returns None silently
        self.assertIsNone(ParsedRow.parse_due_date(""))


if __name__ == "__main__":
    unittest.main()
