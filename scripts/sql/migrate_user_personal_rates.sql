BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS shift_rate_rub NUMERIC(10,2) NOT NULL DEFAULT 0;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS hourly_rate_rub NUMERIC(10,2);

-- Soft backfill from existing per-point assignments for users
-- that still have default personal rates.
WITH ranked AS (
    SELECT
        epa.user_id,
        epa.shift_rate_rub,
        epa.hourly_rate_rub,
        ROW_NUMBER() OVER (
            PARTITION BY epa.user_id
            ORDER BY epa.is_active DESC, epa.is_primary DESC, epa.id DESC
        ) AS rn
    FROM employee_point_assignments epa
)
UPDATE users u
SET
    shift_rate_rub = COALESCE(r.shift_rate_rub, 0),
    hourly_rate_rub = r.hourly_rate_rub
FROM ranked r
WHERE r.user_id = u.id
  AND r.rn = 1
  AND COALESCE(u.shift_rate_rub, 0) = 0
  AND u.hourly_rate_rub IS NULL;

COMMIT;
