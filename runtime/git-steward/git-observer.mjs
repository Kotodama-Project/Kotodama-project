/** Read-only Node-side observer for a trusted disposable Git checkout.
 * Do not run against attacker-controlled .git/config, alternates or executables.
 * This is not a sandbox, runner, push client or authenticated evidence service.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { Refusal, validPath } from './coordinator.mjs';
export function observeDiff(repositoryPath, baseSha, headSha) {
  if (![baseSha, headSha].every(s => typeof s === 'string' && /^[0-9a-f]{40}$/.test(s))) throw new Refusal('REVISION_INVALID');
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('GIT_')));
  Object.assign(env, { GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_NO_REPLACE_OBJECTS: '1', GIT_TERMINAL_PROMPT: '0', LC_ALL: 'C' });
  const git = (...args) => execFileSync('git', ['--no-pager', '-c', 'core.fsmonitor=false', '-C', repositoryPath, ...args],
    { env, timeout: 10000, maxBuffer: 4 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    if (git('rev-parse', '--is-shallow-repository').toString().trim() !== 'false') throw new Refusal('SHALLOW_REPOSITORY');
    for (const revision of [baseSha, headSha]) if (git('cat-file', '-t', revision).toString().trim() !== 'commit') throw new Refusal('NOT_COMMIT');
    git('merge-base', '--is-ancestor', baseSha, headSha);
    const raw = git('diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--name-only', '-z', baseSha, headSha, '--');
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    const paths = text.split('\0').filter(Boolean);
    if (!paths.length || paths.length > 512 || paths.some(p => !validPath(p, false))) throw new Refusal('PATH_INVALID');
    // Binary full-index patch binds exact content, including rename endpoints.
    const patch = git('diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', '--full-index', '--no-color', baseSha, headSha, '--');
    return { base_sha: baseSha, head_sha: headSha, tree_sha: git('rev-parse', `${headSha}^{tree}`).toString().trim(),
      diff_sha256: createHash('sha256').update(patch).digest('hex'), changed_paths: paths.sort() };
  } catch (error) {
    if (error instanceof Refusal) throw error;
    throw new Refusal('GIT_OBSERVATION_FAILED');
  }
}
