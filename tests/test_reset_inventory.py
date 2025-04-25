import sqlite3
import pytest
from reset_inventory import reset_inventory, ITEMS

def test_reset_inventory(tmp_path, capsys):
    db_file = tmp_path / "test_inv.db"
    # Call reset_inventory
    reset_inventory(str(db_file))
    # Capture print output
    captured = capsys.readouterr()
    assert "[reset]" in captured.out
    # Verify table contents
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT name, number FROM inventory ORDER BY id")
    rows = cur.fetchall()
    assert rows == ITEMS
