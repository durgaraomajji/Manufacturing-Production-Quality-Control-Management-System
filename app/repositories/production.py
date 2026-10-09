from app.models.production import ProductionBatch, ProductionOrder, ProductionOutputLog
from app.models.worker import Shift, Worker
from app.repositories.base import BaseRepository

order_repo = BaseRepository(ProductionOrder, "Production order", search_fields=("order_number", "remarks"))
batch_repo = BaseRepository(ProductionBatch, "Production batch", search_fields=("batch_number", "remarks"))
output_log_repo = BaseRepository(ProductionOutputLog, "Output log")
worker_repo = BaseRepository(Worker, "Worker", search_fields=("employee_code", "full_name", "skill", "department"))
shift_repo = BaseRepository(Shift, "Shift")
