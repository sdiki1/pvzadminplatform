BEGIN;

-- 1) Ensure assignment exists for every factual user-point pair from shifts.
WITH shift_pairs AS (
    SELECT
        s.user_id,
        s.point_id,
        COUNT(*)::int AS shifts_count,
        MAX(s.shift_date) AS last_shift_date
    FROM shifts s
    WHERE s.shift_date >= DATE '2026-01-01'
    GROUP BY s.user_id, s.point_id
)
INSERT INTO employee_point_assignments (
    user_id,
    point_id,
    shift_rate_rub,
    hourly_rate_rub,
    is_primary,
    is_active
)
SELECT
    sp.user_id,
    sp.point_id,
    0,
    NULL,
    FALSE,
    TRUE
FROM shift_pairs sp
ON CONFLICT (user_id, point_id)
DO UPDATE
SET is_active = TRUE;

-- 2) Recalculate primary point: max shifts, then latest shift date, then smallest point_id.
WITH shift_pairs AS (
    SELECT
        s.user_id,
        s.point_id,
        COUNT(*)::int AS shifts_count,
        MAX(s.shift_date) AS last_shift_date
    FROM shifts s
    WHERE s.shift_date >= DATE '2026-01-01'
    GROUP BY s.user_id, s.point_id
),
ranked AS (
    SELECT
        sp.user_id,
        sp.point_id,
        ROW_NUMBER() OVER (
            PARTITION BY sp.user_id
            ORDER BY sp.shifts_count DESC, sp.last_shift_date DESC, sp.point_id ASC
        ) AS rn
    FROM shift_pairs sp
),
primary_pairs AS (
    SELECT r.user_id, r.point_id
    FROM ranked r
    WHERE r.rn = 1
)
UPDATE employee_point_assignments epa
SET is_primary = EXISTS (
    SELECT 1
    FROM primary_pairs pp
    WHERE pp.user_id = epa.user_id
      AND pp.point_id = epa.point_id
)
WHERE epa.user_id IN (SELECT DISTINCT user_id FROM shift_pairs);

COMMIT;
