"""Import every model so that Base.metadata knows about all tables (needed by Alembic and create_all)."""
from app.models.approval import ApprovalLog  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.bom import BOM, BOMItem  # noqa: F401
from app.models.inventory import InventoryTransaction  # noqa: F401
from app.models.machine import Machine  # noqa: F401
from app.models.maintenance import Downtime, MaintenanceRecord, SparePartUsage  # noqa: F401
from app.models.material import Material, MaterialCategory  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.plant import Plant, ProductionLine  # noqa: F401
from app.models.product import Product, ProductCategory  # noqa: F401
from app.models.production import BatchWorker, ProductionBatch, ProductionOrder, ProductionOutputLog  # noqa: F401
from app.models.quality import Defect, Inspection, InspectionParameter  # noqa: F401
from app.models.user import PasswordResetToken, RefreshToken, RevokedToken, User  # noqa: F401
from app.models.worker import Shift, Worker  # noqa: F401
