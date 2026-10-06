// Real localhost HTTP + persistent store; synthetic company identities and content.
// Twelve parameterized journeys are one lifecycle family, not twelve live companies.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes, randomUUID } from "node:crypto";
import { startReviewGateway } from "../../runtime/local-review-gateway/server.mjs";
import { syntheticSeed, syntheticCatalog } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";

const personas = [
  ["executive", "取締役会の未承認数字を確定扱いにしない"],
  ["operations", "引継ぎで担当と未完了条件を残す"],
  ["sales", "見積の値引きは未承認のまま示す"],
  ["support", "回答案を送信済みにしない"],
  ["finance", "月次照合の差異を隠さない"],
  ["hr", "入社案内に他人の個人情報を混ぜない"],
  ["manager", "訂正後の受入条件を使う"],
  ["developer", "実装完了を独立検証済みにしない"],
  ["operator", "停止要求を停止完了にしない"],
  ["legal", "重要な未回答を合格にしない"],
  ["research", "出典の版と合格条件を残す"],
  ["contractor", "自分の担当範囲だけを確認する"],
];
for (const [role, intent] of personas) {
  test(`${role}: authorized read -> correction race -> restart -> revoke -> restart`, async () => {
    const stateRoot = mkdtempSync(join(tmpdir(), `kotodama-${role}-`));
    const config = { stateRoot, clientId: "synthetic-client", clientSecret: randomBytes(32).toString("hex") };
    const seed = syntheticSeed();
    seed.actor = { subject: `${role}-owner`, email: `${role}@example.test` };
    seed.projection.handoff_id = `handoff-${role}`;
    seed.projection.overview = `合成の依頼: ${intent}`;
    const reader = { subject: `${role}-reader`, email: `${role}-reader@example.test` };
    const readerRef = `urn:kotodama:principal:${randomUUID()}`;
    const catalog = syntheticCatalog([seed]);
    catalog.principals.push({ principal_ref: readerRef, kind: "human", actor: reader });
    catalog.records[0].access_policy.readers.push(readerRef);
    const headers = actor => ({ "cf-access-client-id": config.clientId, "cf-access-client-secret": config.clientSecret,
      "x-kotodama-access-subject": actor.subject, "x-kotodama-access-email": actor.email, "content-type": "application/json" });
    let gateway;
    try {
      gateway = await startReviewGateway({ ...config, seeds: catalog });
      const get = actor => fetch(`${gateway.origin}/v1/voice/handoffs?q=${seed.projection.handoff_id}`, { headers: headers(actor) });
      const review = (actor, body) => fetch(`${gateway.origin}/v1/voice/handoffs/${seed.projection.handoff_id}/review`, {
        method: "POST", headers: headers(actor), body: JSON.stringify(body) });
      assert.equal((await get(reader)).status, 200, "authorized collaborator can read the candidate");
      const rejected = await review(reader, { action: "accept", expected_revision: 1 });
      assert.equal(rejected.status, 404, "reading does not grant review authority");
      assert.equal((await rejected.text()).includes(intent), false, "denial must not echo private intent");
      const edit = { action: "edit", expected_revision: 1, edited_overview: `訂正: ${intent}。外部への送信は行わない。` };
      const raced = await Promise.all([review(seed.actor, edit), review(seed.actor, edit)]);
      assert.deepEqual(raced.map(x => x.status).sort(), [200, 409], "one revision cannot be committed twice");
      const visible = await (await get(reader)).json();
      assert.equal(visible.overview, edit.edited_overview);
      assert.equal(visible.revision, 2);
      assert.equal(visible.promotion, false);
      assert.equal(visible.current_truth_mutation, false);
      assert.equal(visible.raw_audio_transferred, false);
      assert.equal(visible.private_transcript_transferred, false);
      await gateway.close(); gateway = await startReviewGateway(config);
      const persisted = await (await get(seed.actor)).json();
      assert.equal(persisted.overview, edit.edited_overview, "correction survives restart");
      assert.equal((await review(seed.actor, { action: "accept", expected_revision: 1 })).status, 409, "old screen cannot accept a newer revision");
      gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1,
        policy: { ...seed.access_policy, revision: 2, readers: [seed.principal_ref] } });
      assert.equal((await get(reader)).status, 404, "revocation is enforced immediately");
      assert.equal((await get(seed.actor)).status, 200);
      await gateway.close(); gateway = await startReviewGateway(config);
      assert.equal((await get(reader)).status, 404, "revocation survives restart");
      const stored = readFileSync(join(stateRoot, "voice-reviews.json"), "utf8");
      assert.equal(stored.includes(config.clientSecret), false);
      assert.equal(stored.includes(reader.email), false);
    } finally {
      if (gateway) await gateway.close();
      rmSync(stateRoot, { recursive: true, force: true });
    }
  });
}
