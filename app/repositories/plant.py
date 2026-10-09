from app.models.machine import Machine
from app.models.plant import Plant, ProductionLine
from app.repositories.base import BaseRepository

plant_repo = BaseRepository(Plant, "Plant", search_fields=("code", "name", "city"))
line_repo = BaseRepository(ProductionLine, "Production line", search_fields=("line_code", "name"))
machine_repo = BaseRepository(Machine, "Machine", search_fields=("machine_code", "name", "machine_type"))
