BEGIN;

CREATE SCHEMA evidence;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kotodama_evidence_reader') THEN
    CREATE ROLE kotodama_evidence_reader NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kotodama_evidence_writer') THEN
    CREATE ROLE kotodama_evidence_writer NOLOGIN;
  END IF;
END
$$;

CREATE TABLE evidence.schema_migration (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence.object (
  evidence_id text PRIMARY KEY,
  digest character(64) NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  media_type text NOT NULL,
  data_class text NOT NULL,
  storage_locator text NOT NULL,
  retention_policy_ref text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE TABLE evidence.receipt (
  receipt_id text PRIMARY KEY,
  candidate_revision text NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('pass', 'fail', 'blocked', 'no_effect')),
  document_digest character(64) NOT NULL CHECK (document_digest ~ '^[0-9a-f]{64}$'),
  evidence_locator text,
  observed_at timestamptz NOT NULL
);

CREATE TABLE evidence.receipt_object (
  receipt_id text NOT NULL REFERENCES evidence.receipt(receipt_id),
  evidence_id text NOT NULL REFERENCES evidence.object(evidence_id),
  relation text NOT NULL,
  PRIMARY KEY (receipt_id, evidence_id, relation)
);

INSERT INTO evidence.schema_migration (version) VALUES ('001-evidence-core');

GRANT USAGE ON SCHEMA evidence TO kotodama_evidence_reader, kotodama_evidence_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA evidence TO kotodama_evidence_reader;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA evidence TO kotodama_evidence_writer;

ALTER DEFAULT PRIVILEGES IN SCHEMA evidence
  GRANT SELECT ON TABLES TO kotodama_evidence_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA evidence
  GRANT SELECT, INSERT, UPDATE ON TABLES TO kotodama_evidence_writer;

COMMIT;
