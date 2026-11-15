-- Visual construction schedule, separate from economic activation for backward compatibility.
CREATE TABLE IF NOT EXISTS construction_stages (
 object_id TEXT PRIMARY KEY REFERENCES buildings(id) ON DELETE CASCADE,
 stage TEXT NOT NULL CHECK(stage IN ('foundation','frame','complete')),
 next_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS construction_stages_due ON construction_stages(next_at) WHERE stage != 'complete';