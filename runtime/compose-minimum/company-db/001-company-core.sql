BEGIN;

CREATE SCHEMA company;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kotodama_company_reader') THEN
    CREATE ROLE kotodama_company_reader NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kotodama_company_writer') THEN
    CREATE ROLE kotodama_company_writer NOLOGIN;
  END IF;
END
$$;

CREATE TABLE company.schema_migration (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE company.record (
  record_id text PRIMARY KEY,
  fact_family text NOT NULL,
  record_kind text NOT NULL,
  status text NOT NULL CHECK (status IN ('candidate', 'verified_candidate')),
  payload_digest character(64) NOT NULL CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
  source_locator text NOT NULL,
  authority_ref text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE company.event (
  event_id text PRIMARY KEY,
  record_id text NOT NULL REFERENCES company.record(record_id),
  event_kind text NOT NULL,
  candidate_revision text NOT NULL,
  receipt_locator text NOT NULL,
  observed_at timestamptz NOT NULL
);

CREATE TABLE company.link (
  link_id text PRIMARY KEY,
  source_record_id text NOT NULL REFERENCES company.record(record_id),
  target_record_id text NOT NULL REFERENCES company.record(record_id),
  relation text NOT NULL,
  evidence_locator text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_record_id, target_record_id, relation)
);

INSERT INTO company.schema_migration (version) VALUES ('001-company-core');

GRANT USAGE ON SCHEMA company TO kotodama_company_reader, kotodama_company_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA company TO kotodama_company_reader;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA company TO kotodama_company_writer;

ALTER DEFAULT PRIVILEGES IN SCHEMA company
  GRANT SELECT ON TABLES TO kotodama_company_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA company
  GRANT SELECT, INSERT, UPDATE ON TABLES TO kotodama_company_writer;

COMMIT;
