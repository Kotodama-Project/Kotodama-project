/** Cloudflare SQLite-backed Durable Object store.
 * Construct inside ONE repository-scoped trusted DO, not one per agent/workspace.
 * Expects the native ctx.storage interface; no route or public RPC is exported.
 */
export class CloudflareSqliteStore {
  constructor(storage) {
    this.storage = storage;
    storage.sql.exec('CREATE TABLE IF NOT EXISTS git_steward_state (slot INTEGER PRIMARY KEY CHECK(slot = 1), payload TEXT NOT NULL)');
  }
  transaction(callback) {
    return this.storage.transactionSync(() => {
      const rows = this.storage.sql.exec('SELECT payload FROM git_steward_state WHERE slot = 1').toArray();
      const stored = rows.length === 0 ? null : JSON.parse(rows[0].payload);
      const { state, result } = callback(stored);
      this.storage.sql.exec('INSERT INTO git_steward_state (slot, payload) VALUES (1, ?) ON CONFLICT(slot) DO UPDATE SET payload = excluded.payload', JSON.stringify(state));
      return result;
    });
  }
}
