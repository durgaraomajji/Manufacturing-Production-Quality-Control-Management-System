from app.models.maintenance import Downtime, MaintenanceRecord
from app.repositories.base import BaseRepository

maintenance_repo = BaseRepository(MaintenanceRecord, "Maintenance record", search_fields=("description", "notes"))
downtime_repo = BaseRepository(Downtime, "Downtime record", search_fields=("reason",))
