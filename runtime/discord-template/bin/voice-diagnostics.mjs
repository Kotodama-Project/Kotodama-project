#!/usr/bin/env node
import {parseArgs} from 'node:util';
import {collectVoiceDiagnostics, VoiceDiagnosticsError} from '../src/voice-diagnostics.mjs';

const help = `Read-only, content-free local voice diagnostics (Node 24).
Usage: node bin/voice-diagnostics.mjs --db FILE --since UTC --until UTC --revision SHA
UTC: YYYY-MM-DDTHH:mm:ss.sssZ; SHA: 40 lowercase hex characters.
Window: [since, until), at most 24 hours; at most 10000 selected events.
Output is a local observation, never real-voice acceptance or deployment evidence.
No config, credentials, provider connections or runtime startup are used.
`;
try {
  const parsed = parseArgs({strict: true, allowPositionals: false, tokens: true,
    options: {db: {type: 'string'}, since: {type: 'string'}, until: {type: 'string'},
      revision: {type: 'string'}, help: {type: 'boolean'}}});
  const names = parsed.tokens.filter(t => t.kind === 'option').map(t => t.name);
  if (new Set(names).size !== names.length || (parsed.values.help && names.length !== 1)) {
    throw new VoiceDiagnosticsError('DIAGNOSTIC_ARGUMENTS_INVALID');
  }
  if (parsed.values.help) process.stdout.write(help);
  else {
    const {db: database, since, until, revision} = parsed.values;
    const report = collectVoiceDiagnostics({database, since, until, revision});
    process.stdout.write(`${JSON.stringify(report)}\n`);
  }
} catch (error) {
  const code = error instanceof VoiceDiagnosticsError ? error.code : 'DIAGNOSTIC_ARGUMENTS_INVALID';
  process.stdout.write(`${JSON.stringify({status: 'REFUSED', code, public_beta: 'NO_GO_UNPUBLISHED'})}\n`);
  process.exitCode = 1;
}
