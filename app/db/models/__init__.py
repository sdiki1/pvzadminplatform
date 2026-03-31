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
    Point,
    RoleEnum,
    Shift,
    ShiftConfirmation,
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
)

# Delivery models
from app.db.models.delivery import (
    PointDeliveryStat,
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
    # Core models
    "User",
    "Point",
    "EmployeePointAssignment",
    "ShiftConfirmation",
    "Shift",
    "ManualAdjustment",
    "MotivationRecord",
    "Expense",
    "PayrollRun",
    "PayrollItem",
    "GeofenceException",
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
    # Incidents
    "DefectIncident",
    "SOSIncident",
    # Supply
    "SupplyItem",
    "SupplyRequestHeader",
    "SupplyRequestItem",
    # Delivery
    "PointDeliveryStat",
    # Appeals
    "Appeal",
    "AppealFeedback",
    # Marketing
    "MarketingSurvey",
    # Common
    "Attachment",
    "Comment",
    "Notification",
    "ImportBatch",
    "ImportError",
]
