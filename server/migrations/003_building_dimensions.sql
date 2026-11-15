-- Optional footprint and equipment level of a building (added to postgres_db.SCHEMA by the construction work). Idempotent: init() creates the same table.
-- Reversibility: DROP TABLE building_dimensions (buildings fall back to their legacy default footprint; nothing else depends on it).
CREATE TABLE IF NOT EXISTS building_dimensions (
 object_id TEXT PRIMARY KEY REFERENCES buildings(id) ON DELETE CASCADE,
 width INTEGER NOT NULL CHECK(width BETWEEN 1 AND 3),
 height INTEGER NOT NULL CHECK(height BETWEEN 1 AND 3),
 equipment_level INTEGER NOT NULL DEFAULT 1 CHECK(equipment_level BETWEEN 1 AND 3)
);
