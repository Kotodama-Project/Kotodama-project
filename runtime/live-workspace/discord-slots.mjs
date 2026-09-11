import { randomUUID } from 'node:crypto';
import { check, scopeIdentity, text } from './core.mjs';

/**
 * Transport capacity only, NOT a Task scheduler or bot-token registry.
 * One owning process/actor must serialize reservations. A distributed deployment
 * must implement the same transitions in its existing transactional owner.
 * One bot may occupy only one channel per guild; group names do not bypass this.
 */
export class DiscordVoiceSlots {
  #bots; #rooms = new Map(); #occupied = new Map();
  constructor(botRefs) {
    check(Array.isArray(botRefs) && botRefs.length > 0 && botRefs.length <= 32, 'invalid_bot_pool');
    this.#bots = botRefs.map(x => text(x));
    check(new Set(this.#bots).size === this.#bots.length, 'duplicate_bot_ref');
  }
  reserve(scopeInput) {
    const scope = scopeIdentity(scopeInput); check(scope.provider === 'discord', 'discord_scope_required');
    const previous = this.#rooms.get(scope.key);
    if (previous) { check(previous.state === 'active', 'discord_slot_reconciling'); return previous.lease; }
    const botRef = this.#bots.find(bot => !this.#occupied.has(JSON.stringify([bot, scope.tenant])));
    check(botRef, 'discord_voice_capacity_exhausted');
    const lease = Object.freeze({ id: randomUUID(), roomKey: scope.key, botRef });
    const occupancyKey = JSON.stringify([botRef, scope.tenant]);
    const entry = { lease, occupancyKey, state: 'active' };
    this.#rooms.set(scope.key, entry); this.#occupied.set(occupancyKey, entry); return lease;
  }
  async release(lease, observeDisconnected) {
    const entry = this.#rooms.get(lease?.roomKey);
    check(entry && entry.lease === lease && entry.state !== 'releasing', 'invalid_discord_lease');
    check(typeof observeDisconnected === 'function', 'disconnect_observer_required');
    entry.state = 'releasing';
    let observed = false;
    try { observed = await observeDisconnected(lease) === true; } catch { /* retain uncertain slot */ }
    if (!observed) { entry.state = 'uncertain'; return false; }
    check(this.#rooms.get(lease.roomKey) === entry, 'discord_lease_changed');
    this.#rooms.delete(lease.roomKey); this.#occupied.delete(entry.occupancyKey); return true;
  }
}
