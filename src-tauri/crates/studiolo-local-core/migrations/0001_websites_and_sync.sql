CREATE TABLE local_binding (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    installation_id TEXT NOT NULL,
    core_url TEXT,
    workspace_id TEXT,
    workspace_name TEXT,
    client_id TEXT,
    client_name TEXT,
    app_version TEXT,
    connected_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('disconnected', 'connected', 'revoked'))
);

CREATE TABLE local_sync_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    cursor INTEGER NOT NULL DEFAULT 0 CHECK (cursor >= 0),
    blocked INTEGER NOT NULL DEFAULT 0,
    queue_seeded INTEGER NOT NULL DEFAULT 1,
    last_error TEXT,
    last_attempt_at TEXT,
    last_success_at TEXT,
    next_retry_at TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0
);

INSERT INTO local_sync_state (singleton) VALUES (1);

CREATE TABLE website_categories (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    sync_revision INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE websites (
    id TEXT PRIMARY KEY NOT NULL,
    category_id TEXT REFERENCES website_categories(id) DEFERRABLE INITIALLY DEFERRED,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    icon TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    favorite INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    visit_count INTEGER NOT NULL DEFAULT 0,
    last_visited_at TEXT,
    sync_revision INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX websites_category ON websites (category_id) WHERE deleted_at IS NULL;

CREATE TABLE local_mutations (
    mutation_id TEXT PRIMARY KEY NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('website.category', 'website')),
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
    base_revision INTEGER NOT NULL CHECK (base_revision >= 0),
    payload_json TEXT,
    depends_on_mutation_id TEXT,
    previous_mutation_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'conflict', 'rejected')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    conflict_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((operation = 'delete') = (payload_json IS NULL))
);

CREATE INDEX local_mutations_entity ON local_mutations (entity_type, entity_id);
CREATE INDEX local_mutations_parent ON local_mutations (depends_on_mutation_id);
CREATE INDEX local_mutations_predecessor ON local_mutations (previous_mutation_id);
