import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL(".", import.meta.url));
// Type-check authored source; wrangler's runtime entry is the generated RPC wrapper.
// Pointing the type generator at that wrapper also type-checks the generator's
// widened `unchecked` literals, which is unrelated to this package's source types.
const config = JSON.parse(readFileSync(join(root, "wrangler.jsonc"), "utf8"));
config.main = "src/kotodama.ts";
const temporary = join(root, `.wrangler-types-${process.pid}.json`);
writeFileSync(temporary, JSON.stringify(config), { flag: "wx" });
try { execFileSync("pnpm", ["exec", "wrangler", "types", "--config", temporary], { cwd: root, stdio: "inherit" }); }
finally { unlinkSync(temporary); }
