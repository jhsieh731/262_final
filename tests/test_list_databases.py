import sqlite3
import pytest
from list_databases import list_databases

def test_list_databases_single_db(tmp_path, capsys):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_file = db_dir / "foo.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT);")
    cur.executemany("INSERT INTO test (name) VALUES (?);", [("a",), ("b",)])
    conn.commit()
    conn.close()

    list_databases(str(db_dir))
    out = capsys.readouterr().out
    assert "foo.db" in out
    assert "Tables (1)" in out
    assert "test (2 rows)" in out
    assert "Columns: id, name" in out
