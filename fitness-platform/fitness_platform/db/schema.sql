-- Fitness platform schema.
--
-- SQLite here; the column types and constraints are deliberately plain so the
-- same DDL ports to Postgres with only the AUTOINCREMENT/BOOLEAN spellings
-- changed. All content-bearing tables carry `gender_path`, because the
-- women/men split is a data-level rule, not a UI rule (2, 14, 53).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- identity --
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    email                TEXT    NOT NULL UNIQUE,
    name                 TEXT    NOT NULL DEFAULT '',
    password_hash        TEXT    NOT NULL,
    role                 TEXT    NOT NULL DEFAULT 'user'
                                 CHECK (role IN ('user', 'admin', 'content_manager', 'nutrition_specialist')),
    gender_path          TEXT             CHECK (gender_path IN ('female', 'male')),
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    status               TEXT    NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'suspended', 'deleted')),
    last_active_at       TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_gender ON users (gender_path);
CREATE INDEX IF NOT EXISTS idx_users_role   ON users (role);

-- Profile data is split from the identity row so personal detail can be
-- exported or erased on its own (47).
CREATE TABLE IF NOT EXISTS profiles (
    user_id           INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    display_name      TEXT    NOT NULL DEFAULT '',
    avatar_url        TEXT    NOT NULL DEFAULT '',
    birth_year        INTEGER,
    height_cm         INTEGER,
    weight_kg         REAL,
    experience_level  TEXT    NOT NULL DEFAULT 'beginner'
                              CHECK (experience_level IN ('beginner', 'intermediate', 'advanced')),
    weekly_frequency  INTEGER NOT NULL DEFAULT 3,
    session_minutes   INTEGER NOT NULL DEFAULT 30,
    equipment         TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    goals             TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    dietary_tags      TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    allergies         TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    disliked_foods    TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    meals_per_day     INTEGER NOT NULL DEFAULT 3,
    preferred_days    TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    csrf_token  TEXT    NOT NULL,
    user_agent  TEXT    NOT NULL DEFAULT '',
    ip_address  TEXT    NOT NULL DEFAULT '',
    expires_at  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

-- ------------------------------------------------------------- onboarding --
CREATE TABLE IF NOT EXISTS onboarding_answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    step_key     TEXT    NOT NULL,
    question_key TEXT    NOT NULL,
    answer       TEXT    NOT NULL DEFAULT '',   -- JSON encoded value
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, question_key)
);

CREATE TABLE IF NOT EXISTS onboarding_progress (
    user_id      INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    current_step INTEGER NOT NULL DEFAULT 0,
    total_steps  INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------- billing lifecycle --
CREATE TABLE IF NOT EXISTS subscriptions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    plan_code            TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending', 'active', 'past_due', 'cancelled', 'expired')),
    provider             TEXT    NOT NULL DEFAULT 'mock',
    provider_customer_id TEXT    NOT NULL DEFAULT '',
    provider_ref         TEXT    NOT NULL DEFAULT '',
    amount_cents         INTEGER NOT NULL DEFAULT 0,
    currency             TEXT    NOT NULL DEFAULT 'ILS',
    current_period_end   TEXT,
    cancelled_at         TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (user_id);

CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    subscription_id INTEGER          REFERENCES subscriptions (id) ON DELETE SET NULL,
    amount_cents    INTEGER NOT NULL,
    currency        TEXT    NOT NULL DEFAULT 'ILS',
    status          TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
    provider        TEXT    NOT NULL DEFAULT 'mock',
    provider_ref    TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id);

-- Webhook ids are stored so a replayed delivery is a no-op (45).
CREATE TABLE IF NOT EXISTS payment_webhook_events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------ content: gym --
CREATE TABLE IF NOT EXISTS coaches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    gender_path TEXT NOT NULL CHECK (gender_path IN ('female', 'male', 'all')),
    photo_url   TEXT NOT NULL DEFAULT '',
    bio         TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS videos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    thumbnail_url TEXT    NOT NULL DEFAULT '',
    video_url     TEXT    NOT NULL DEFAULT '',
    duration      INTEGER NOT NULL DEFAULT 0,        -- minutes
    difficulty    TEXT    NOT NULL DEFAULT 'beginner'
                          CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    category      TEXT    NOT NULL DEFAULT 'full_body',
    gender_path   TEXT    NOT NULL CHECK (gender_path IN ('female', 'male', 'all')),
    coach_id      INTEGER          REFERENCES coaches (id) ON DELETE SET NULL,
    equipment     TEXT    NOT NULL DEFAULT '[]',     -- JSON array
    tags          TEXT    NOT NULL DEFAULT '[]',     -- JSON array
    published     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_videos_scope ON videos (gender_path, published);

CREATE TABLE IF NOT EXISTS video_progress (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    video_id      INTEGER NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    status        TEXT    NOT NULL DEFAULT 'started'
                          CHECK (status IN ('started', 'completed')),
    seconds_watched INTEGER NOT NULL DEFAULT 0,
    completed_at  TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, video_id)
);

CREATE TABLE IF NOT EXISTS workout_programs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    description    TEXT    NOT NULL DEFAULT '',
    gender_path    TEXT    NOT NULL CHECK (gender_path IN ('female', 'male', 'all')),
    duration_weeks INTEGER NOT NULL DEFAULT 4,
    difficulty     TEXT    NOT NULL DEFAULT 'beginner'
                           CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    goal_tags      TEXT    NOT NULL DEFAULT '[]',    -- JSON array
    equipment      TEXT    NOT NULL DEFAULT '[]',    -- JSON array
    cover_url      TEXT    NOT NULL DEFAULT '',
    published      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_programs_scope ON workout_programs (gender_path, published);

CREATE TABLE IF NOT EXISTS workout_program_days (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES workout_programs (id) ON DELETE CASCADE,
    day_number INTEGER NOT NULL,
    title      TEXT    NOT NULL DEFAULT '',
    focus      TEXT    NOT NULL DEFAULT '',
    is_rest    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (program_id, day_number)
);

CREATE TABLE IF NOT EXISTS workout_program_day_videos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id   INTEGER NOT NULL REFERENCES workout_program_days (id) ON DELETE CASCADE,
    video_id INTEGER NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE (day_id, video_id)
);

CREATE TABLE IF NOT EXISTS user_programs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    program_id  INTEGER NOT NULL REFERENCES workout_programs (id) ON DELETE CASCADE,
    status      TEXT    NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed', 'abandoned')),
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    UNIQUE (user_id, program_id)
);

-- --------------------------------------------------------- content: food ---
CREATE TABLE IF NOT EXISTS recipes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    ingredients  TEXT    NOT NULL DEFAULT '[]',      -- JSON array of {name, amount, unit}
    instructions TEXT    NOT NULL DEFAULT '[]',      -- JSON array of steps
    image_url    TEXT    NOT NULL DEFAULT '',
    tags         TEXT    NOT NULL DEFAULT '[]',
    meal_type    TEXT    NOT NULL DEFAULT 'lunch'
                         CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    dietary_tags TEXT    NOT NULL DEFAULT '[]',
    allergens    TEXT    NOT NULL DEFAULT '[]',
    gender_path  TEXT    NOT NULL CHECK (gender_path IN ('female', 'male', 'all')),
    prep_minutes INTEGER NOT NULL DEFAULT 15,
    approved     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recipes_scope ON recipes (gender_path, approved);

CREATE TABLE IF NOT EXISTS meal_plans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    week_start TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, week_start)
);

CREATE TABLE IF NOT EXISTS meal_plan_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_plan_id INTEGER NOT NULL REFERENCES meal_plans (id) ON DELETE CASCADE,
    recipe_id    INTEGER NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
    day_index    INTEGER NOT NULL,                   -- 0 = week_start
    meal_type    TEXT    NOT NULL,
    UNIQUE (meal_plan_id, day_index, meal_type)
);

CREATE TABLE IF NOT EXISTS shopping_lists (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    meal_plan_id INTEGER          REFERENCES meal_plans (id) ON DELETE SET NULL,
    title        TEXT    NOT NULL DEFAULT 'רשימת קניות',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shopping_list_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    shopping_list_id INTEGER NOT NULL REFERENCES shopping_lists (id) ON DELETE CASCADE,
    name             TEXT    NOT NULL,
    amount           TEXT    NOT NULL DEFAULT '',
    category         TEXT    NOT NULL DEFAULT 'other',
    checked          INTEGER NOT NULL DEFAULT 0
);

-- ------------------------------------------------------------------- AI ----
CREATE TABLE IF NOT EXISTS ai_conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    gender_path TEXT    NOT NULL CHECK (gender_path IN ('female', 'male')),
    title       TEXT    NOT NULL DEFAULT 'שיחה עם המאמן',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES ai_conversations (id) ON DELETE CASCADE,
    role            TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT    NOT NULL,
    provider        TEXT    NOT NULL DEFAULT '',
    tokens          INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'ok'
                            CHECK (status IN ('ok', 'blocked', 'error')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_conv ON ai_messages (conversation_id);

-- ----------------------------------------------------- analytics and audit --
CREATE TABLE IF NOT EXISTS analytics_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER          REFERENCES users (id) ON DELETE SET NULL,
    name        TEXT    NOT NULL,
    gender_path TEXT,
    properties  TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analytics_name ON analytics_events (name, created_at);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id    INTEGER          REFERENCES users (id) ON DELETE SET NULL,
    action      TEXT    NOT NULL,
    entity_type TEXT    NOT NULL DEFAULT '',
    entity_id   TEXT    NOT NULL DEFAULT '',
    details     TEXT    NOT NULL DEFAULT '{}',
    ip_address  TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS progress_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    entry_date TEXT    NOT NULL,
    weight_kg  REAL,
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, entry_date)
);
