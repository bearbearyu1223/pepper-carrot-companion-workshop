from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.models import Episode

print(CreateTable(Episode.__table__).compile(dialect=postgresql.dialect()))
