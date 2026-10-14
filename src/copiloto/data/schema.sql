-- Esquema do banco sintético do Copiloto de Operações.
-- Todos os dados são fictícios e gerados com seed fixa.

CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    region        TEXT NOT NULL,
    segment       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id            TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(customer_id),
    created_at          TEXT NOT NULL,          -- ISO date (YYYY-MM-DD)
    status              TEXT NOT NULL,          -- entregue | em_transito | cancelado | processando
    channel             TEXT NOT NULL,          -- site | app | marketplace
    category            TEXT NOT NULL,
    amount              REAL NOT NULL,
    carrier             TEXT NOT NULL,
    promised_days       INTEGER NOT NULL,
    delivered_days      INTEGER,                -- NULL se não entregue
    cancel_reason       TEXT,                   -- NULL se não cancelado
    cancelled_at        TEXT                    -- ISO date, NULL se não cancelado
);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id     TEXT PRIMARY KEY,
    order_id      TEXT REFERENCES orders(order_id),
    created_at    TEXT NOT NULL,
    subject       TEXT NOT NULL,
    status        TEXT NOT NULL,                -- aberto | resolvido | escalado
    description   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at);

CREATE TABLE IF NOT EXISTS action_proposals (
    proposal_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    title           TEXT NOT NULL,
    content_json    TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    state           TEXT NOT NULL,              -- awaiting_approval | approved | rejected | executed | expired | revoked
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    decided_by      TEXT,
    decided_at      TEXT,
    decision_hash   TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL REFERENCES action_proposals(proposal_id),
    idempotency_key TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    content_json    TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    run_id      TEXT,
    actor       TEXT,
    event       TEXT NOT NULL,
    details     TEXT
);
