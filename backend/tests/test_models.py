from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Chunk


def test_postgresql_chunk_ddl_compiles():
    dialect = postgresql.dialect()
    assert "vector" in str(CreateTable(Chunk.__table__).compile(dialect=dialect)).lower()
    indexes = [str(CreateIndex(index).compile(dialect=dialect)) for index in Chunk.__table__.indexes]
    assert any("to_tsvector('simple'" in ddl for ddl in indexes)
    assert any("vector_cosine_ops" in ddl for ddl in indexes)
