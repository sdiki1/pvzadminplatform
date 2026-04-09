from __future__ import annotations

# Re-export Base
from app.db.base import Base

# Re-export all original (core) models and enums
from app.db.models.core import (
    AdjustmentType,
    ApprovalStatus,
    BrandEnum,
    ConfirmationStatus,
    EmployeePointAssignment,
    Expense,
    GeofenceException,
    GeoStatus,
    ManualAdjustment,
    MotivationRecord,
    MotivationSource,
    PayrollItem,
    PayrollRun,
    PlannedShift,
    PlannedShiftStatus,
    Point,
    RoleEnum,
    Shift,
    ShiftConfirmation,
    ShiftOpenCode,
    ShiftState,
    User,
)

# New web models
from app.db.models.web import (
    AuditLog,
    EmailConfirmation,
    WebRoleEnum,
    WebUser,
)

# Reference / dictionary models
from app.db.models.reference import (
    DailyStatMetricDef,
    DailyStatMetricValue,
    DailyStatReport,
    EmployeeAlias,
    Marketplace,
    PointSettings,
    ReceptionStat,
)

# Incident models
from app.db.models.incidents import (
    DefectIncident,
    SOSIncident,
)

# Supply models
from app.db.models.supply import (
    SupplyItem,
    SupplyRequestHeader,
    SupplyRequestItem,
    SupplyStatusLog,
)

# Appeal models
from app.db.models.appeals import (
    Appeal,
    AppealFeedback,
)

# Marketing models
from app.db.models.marketing import (
    MarketingSurvey,
)

# Tardiness models
from app.db.models.tardiness import (
    TardinessRecord,
)

# Common models (attachments, comments, notifications, imports)
from app.db.models.common import (
    Attachment,
    Comment,
    ImportBatch,
    ImportError,
    Notification,
)

__all__ = [
    "Base",
    # Core enums
    "RoleEnum",
    "BrandEnum",
    "ConfirmationStatus",
    "GeoStatus",
    "ApprovalStatus",
    "ShiftState",
    "AdjustmentType",
    "MotivationSource",
    "PlannedShiftStatus",
    # Core models
    "User",
    "Point",
    "EmployeePointAssignment",
    "PlannedShift",
    "ShiftConfirmation",
    "Shift",
    "ManualAdjustment",
    "MotivationRecord",
    "Expense",
    "PayrollRun",
    "PayrollItem",
    "GeofenceException",
    "ShiftOpenCode",
    # Web
    "WebRoleEnum",
    "WebUser",
    "AuditLog",
    "EmailConfirmation",
    # Reference
    "Marketplace",
    "EmployeeAlias",
    "PointSettings",
    "DailyStatReport",
    "DailyStatMetricDef",
    "DailyStatMetricValue",
    "ReceptionStat",
    # Incidents
    "DefectIncident",
    "SOSIncident",
    # Supply
    "SupplyItem",
    "SupplyRequestHeader",
    "SupplyRequestItem",
    "SupplyStatusLog",
    # Appeals
    "Appeal",
    "AppealFeedback",
    # Marketing
    "MarketingSurvey",
    # Tardiness
    "TardinessRecord",
    # Common
    "Attachment",
    "Comment",
    "Notification",
    "ImportBatch",
    "ImportError",
]
