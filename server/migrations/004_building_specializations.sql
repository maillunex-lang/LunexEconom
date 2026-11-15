-- Specialization of a building (added to postgres_db.SCHEMA by the construction work). Idempotent: init() creates the same table.
-- Reversibility: DROP TABLE building_specializations (buildings fall back to their default specialization; nothing else depends on it).
CREATE TABLE IF NOT EXISTS building_specializations (
 object_id TEXT PRIMARY KEY REFERENCES buildings(id) ON DELETE CASCADE,
 specialization TEXT NOT NULL
);
