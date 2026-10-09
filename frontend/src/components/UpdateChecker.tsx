import { useEffect, useState } from 'react';
import pkg from '../../package.json';

const CURRENT = (pkg as { version: string }).version;
const UPSTREAM_REPO = 'keezxc1223/locwarp';
const MAC_REPO = 'jacktdry/locwarp-macos';

function isMac(): boolean {
  return window.electronAPI?.platform === 'darwin' ||
    (!window.electronAPI && /Mac/i.test(navigator.platform || ''));
}

// Compare upstream semver bases first, then the Mac fork's macos.N suffix.
// Pre-releases are included explicitly: GitHub /releases/latest excludes them.
export function isNewer(a: string, b: string): boolean {
  const parse = (v: string) => {
    const m = v.replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)(?:-macos\.(\d+))?$/);
    return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] == null ? Infinity : Number(m[4])] : null;
  };
  const x = parse(a); const y = parse(b);
  if (!x || !y) return false;
  for (let i = 0; i < x.length; i++) {
    if (x[i] !== y[i]) return x[i] > y[i];
  }
  return false;
}

export interface UpdateInfo {
  current: string;
  latest: string | null;
  releaseUrl: string | null;
}

/**
 * Hook: checks GitHub on mount for a newer release. Returns the latest tag
 * (or null if up-to-date / unreachable) plus a direct release URL. No
 * popup, no dismiss flow — caller decides how to surface the badge.
 */
export function useUpdateCheck(): UpdateInfo {
  const [latest, setLatest] = useState<string | null>(null);
  const [releaseUrl, setReleaseUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mac = isMac();
        const repo = mac ? MAC_REPO : UPSTREAM_REPO;
        const currentVersion = mac ? CURRENT : CURRENT.split('-')[0];
        const url = `https://api.github.com/repos/${repo}/releases/${mac ? '?per_page=20' : 'latest'}`;
        const r = await fetch(url, { headers: { Accept: 'application/vnd.github+json' } });
        if (!r.ok) return;
        const data = await r.json();
        // GitHub sorts Releases newest first; compare all candidates for
        // monotonic version ordering even when publishing out of sequence.
        const versions: {tag_name:string; html_url?:string}[] = mac ?
          (Array.isArray(data) ? data.filter(item => !item.draft) : []) : [data];
        const newer = versions.filter(item => item.tag_name && isNewer(item.tag_name, currentVersion));
        newer.sort((a,b) => isNewer(a.tag_name,b.tag_name) ? -1 : 1);
        if (cancelled || !newer.length) return;
        setLatest(newer[0].tag_name);
        setReleaseUrl(newer[0].html_url || `https://github.com/${repo}/releases`);
      } catch {
        /* offline / rate-limited / DNS — silent */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return { current: CURRENT, latest, releaseUrl };
}
