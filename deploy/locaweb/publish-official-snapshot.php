<?php
declare(strict_types=1);
/**
 * HMAC-authenticated public activation helper.
 * Call ONLY through election-publish.php after a complete private snapshot build.
 * Immutable releases are fully written before atomically replacing public version.json.
 */
function publishOfficialSnapshot(string $base, string $batchId): array {
    if (!is_file($base . '/ENABLE_OFFICIAL_PUBLICATION')) throw new RuntimeException('production_disabled');
    if (!preg_match('/^[a-f0-9]{32}$/D', $batchId)) throw new RuntimeException('invalid_batch_id');
    $meta = json_decode((string)@file_get_contents($base . '/batches/' . $batchId . '/batch.json'), true);
    if (!is_array($meta) || !is_array($meta['paths'] ?? null) || count($meta['paths']) !== 140) {
        throw new RuntimeException('full_batch_required');
    }
    $batch = $base . '/batches/' . $batchId . '/files';
    $v = json_decode((string)@file_get_contents($batch . '/version.json'), true);
    if (!is_array($v) || ($v['environment'] ?? '') !== 'oficial' ||
        !is_string($v['generated_at'] ?? null)) throw new RuntimeException('official_only');
    require_once __DIR__ . '/build-private-snapshot.php';
    $lock = @fopen($base . '/official-publish.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) throw new RuntimeException('publication_busy');
    try {
        $site = dirname(__DIR__) . '/data';
        if (!is_dir($site) || !is_file($site . '/version.json')) throw new RuntimeException('public_not_ready');
        $old = json_decode((string)file_get_contents($site . '/version.json'), true);
        if (!is_array($old) || ($old['environment'] ?? '') !== 'oficial') throw new RuntimeException('invalid_public_version');
        try {
            $newTime = new DateTimeImmutable($v['generated_at']);
            $oldTime = new DateTimeImmutable((string)($old['generated_at'] ?? ''));
        } catch (Exception $e) {
            throw new RuntimeException('invalid_timestamp');
        }
        if ($newTime <= $oldTime) throw new RuntimeException('stale_version');
        // Build the full snapshot using the registered private baseline.
        // Public publication NEVER uses the sandbox current pointer as an authority:
        // only a freshly staged official batch can trigger it.
        $built = buildPrivateSnapshot($base, $batchId);
        $sid = $built['snapshot_id'] ?? null;
        if (!is_string($sid) || !preg_match('/^[a-f0-9]{64}$/D', $sid)) throw new RuntimeException('invalid_snapshot');
        $src = $base . '/snapshot-sandbox/releases/' . $sid;
        $manifest = json_decode((string)@file_get_contents($src . '/manifest.json'), true);
        $alerts = json_decode((string)@file_get_contents($src . '/alerts.json'), true);
        if (($manifest['generated_at'] ?? null) !== $v['generated_at'] ||
            ($alerts['generated_at'] ?? null) !== $v['generated_at'] ||
            ($manifest['result_count'] ?? null) !== 137 ||
            !is_array($manifest['results'] ?? null) ||
            count($manifest['results']) !== 137) throw new RuntimeException('invalid_metadata');
        $paths = [];
        foreach ($manifest['results'] as $entry) {
            $p = $entry['path'] ?? null;
            if (!is_string($p) || !preg_match('#^[a-z]{2}/[a-z0-9-]+\\.json$#D', $p) ||
                isset($paths[$p]) || !is_file($src.'/'.$p) || is_link($src.'/'.$p)) {
                throw new RuntimeException('invalid_release');
            }
            $paths[$p] = true;
        }
        $releases = $site . '/releases';
        if (!is_dir($releases) && !@mkdir($releases, 0755, true)) throw new RuntimeException('storage_failed');
        $dest = $releases . '/' . $sid;
        if (!is_dir($dest)) {
            $tmp = $releases . '/.release-' . bin2hex(random_bytes(8));
            if (!@mkdir($tmp, 0755)) throw new RuntimeException('storage_failed');
            foreach (array_merge(array_keys($paths), ['manifest.json','alerts.json','version.json']) as $p) {
                $parent = dirname($tmp . '/' . $p);
                if (!is_dir($parent) && !@mkdir($parent, 0755, true)) throw new RuntimeException('storage_failed');
                if (!@copy($src.'/'.$p, $tmp.'/'.$p)) throw new RuntimeException('copy_failed');
                @chmod($tmp.'/'.$p, 0644);
            }
            if (!@rename($tmp, $dest)) throw new RuntimeException('release_move_failed');
        }
        foreach (array_merge(array_keys($paths), ['manifest.json','alerts.json','version.json']) as $p) {
            if (!is_file($dest.'/'.$p) || is_link($dest.'/'.$p) ||
                !hash_equals(hash_file('sha256', $src.'/'.$p), hash_file('sha256', $dest.'/'.$p))) {
                throw new RuntimeException('release_checksum_error');
            }
        }
        $next = $v;
        $next['snapshot_id'] = $sid;
        $bytes = json_encode($next, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
        $temp = @tempnam($site, '.version-');
        if ($temp === false || file_put_contents($temp, $bytes) !== strlen($bytes)) throw new RuntimeException('marker_write_failed');
        @chmod($temp, 0644);
        // This is the sole public cutover; immutable release must already be available.
        if (!@rename($temp, $site . '/version.json')) throw new RuntimeException('marker_swap_failed');
        return ['status'=>'published','snapshot_id'=>$sid,'generated_at'=>$v['generated_at'],'mode'=>'official'];
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}
