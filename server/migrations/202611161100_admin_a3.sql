-- V2-ADM3: append-only catalog revisions, announcements and idempotent deactivations.
-- Revisions contain full active override sets. Prior revisions are immutable.
CREATE TABLE catalog_revisions (
    revision bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    request_hash char(64) NOT NULL,
    reason varchar(500) NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalog_overrides (
    revision bigint NOT NULL REFERENCES catalog_revisions(revision),
    entity text NOT NULL CHECK (entity IN ('products','buildings','recipes')),
    entity_id text NOT NULL,
    field text NOT NULL,
    value bigint NOT NULL CHECK (value>=0),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (revision,entity,entity_id,field)
);
CREATE TABLE announcements (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    request_hash char(64) NOT NULL,
    title varchar(80) NOT NULL CHECK (length(title)>0),
    body varchar(500) NOT NULL CHECK (length(body)>0),
    level text NOT NULL CHECK (level IN ('info','warn')),
    city_id text REFERENCES world_cities(id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    active boolean NOT NULL DEFAULT true,
    CHECK (ends_at>starts_at)
);
CREATE INDEX announcements_live_idx ON announcements (starts_at,ends_at) WHERE active=true;
CREATE TABLE announcement_deactivations (
    request_id text PRIMARY KEY,
    announcement_id bigint NOT NULL REFERENCES announcements(id),
    request_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
