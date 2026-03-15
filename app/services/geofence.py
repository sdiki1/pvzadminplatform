from __future__ import annotations

from dataclasses import dataclass

from app.db.models import GeoStatus, Point
from app.utils.geo import haversine_distance_m


@dataclass
class GeofenceCheckResult:
    distance_m: float
    status: GeoStatus


class GeofenceService:
    @staticmethod
    def check(point: Point, lat: float, lon: float) -> GeofenceCheckResult:
        distance = haversine_distance_m(float(point.latitude), float(point.longitude), lat, lon)
        status = GeoStatus.OK if distance <= point.radius_m else GeoStatus.OUTSIDE
        return GeofenceCheckResult(distance_m=distance, status=status)
