from app.models.quality import Defect, Inspection
from app.repositories.base import BaseRepository

inspection_repo = BaseRepository(Inspection, "Inspection", search_fields=("remarks",))
defect_repo = BaseRepository(Defect, "Defect", search_fields=("defect_type", "root_cause", "description"))
