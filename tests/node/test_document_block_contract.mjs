import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
const path = process.env.DOCUMENT_SERVER_SOURCE;
if (!path) { console.log("Official Document source not supplied; run the integration test against the manifest-bound patched source."); }
const raw = path ? readFileSync(path, "utf8").replaceAll("\r\n", "\n") : "export class Gadget {}";
if (path) {
  const manifest = JSON.parse(readFileSync(new URL("../../runtime/cloudflare-os-kotodama/patches/manifest.json", import.meta.url), "utf8"));
  const expected = manifest.files.find(file => file.patch === "document-block-validation.patch").afterSha256;
  assert.equal(createHash("sha256").update(raw).digest("hex"), expected, "Document source must match the reviewed patched bytes");
}
const source = raw.replace(
  'import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";',
  'class DurableObject {} class WorkerEntrypoint {}');
const { Gadget } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
function makeGadget() {
  const data = new Map();
  return new Gadget({ storage: {
    async get(key) { return structuredClone(data.get(key)); },
    async put(key, value) { data.set(key, structuredClone(value)); },
  } }, {});
}

test("invalid full-document blocks refuse and preserve the entire previous snapshot", { skip: !path }, async () => {
  const gadget = makeGadget();
  const before = await gadget.setDocument({ title:"existing document", blocks:[{id:"one",html:'<p data-block-id="one">keep this content</p>'}],senderId:"fixture" });
  for (const blocks of [undefined, null, ['<p>wrong shape</p>'], [{id:'one',html:'valid'},{id:'one',html:'duplicate'}], [{id:'missing-html'}]]) {
    await assert.rejects(gadget.setDocument({title:"bad update",blocks,senderId:"fixture"}), /blocks|block/);
    assert.deepEqual(await gadget.getDocument(), before);
  }
});

test("valid object blocks and explicit empty document retain the original contract", { skip: !path }, async () => {
  const gadget = makeGadget();
  const first = await gadget.setDocument({title:"document",blocks:[{id:"one",html:"<p>text</p>"}],senderId:"fixture"});
  assert.equal(first.blocks.length,1);
  const cleared=await gadget.setDocument({title:"document",blocks:[],senderId:"fixture"});
  assert.equal(cleared.blocks.length,0); assert.equal(cleared.revision,first.revision+1);
});
