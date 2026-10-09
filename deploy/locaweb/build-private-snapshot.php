<?php
declare(strict_types=1);

/**
 * Full immutable snapshot assembler for private integration tests.
 * No public_html writes. Designed to prepare the future production protocol.
 */
function buildPrivateSnapshot(string $base, string $id): array {
    if (!preg_match('/^[a-f0-9]{32}$/D', $id)) throw new RuntimeException('invalid_batch_id');
    $batch = $base . '/batches/' . $id;
    $meta = json_decode((string)@file_get_contents($batch . '/batch.json'), true);
    $paths = $meta['paths'] ?? null;
    if (!is_array($paths) || count($paths) < 4 || count($paths) > 140) throw new RuntimeException('invalid_batch');
    if (count($paths) !== count(array_unique($paths))) throw new RuntimeException('duplicate_path');
    $root = $base . '/snapshot-sandbox';
    if (!is_dir($root) && !mkdir($root, 0700, true)) throw new RuntimeException('storage_failed');
    $lock = fopen($base . '/snapshot-build.lock', 'c');
    if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) throw new RuntimeException('snapshot_busy');
    try {
        $version = json_decode((string)@file_get_contents($batch . '/files/version.json'), true);
        $manifest = json_decode((string)@file_get_contents($batch . '/files/manifest.json'), true);
        $alerts = json_decode((string)@file_get_contents($batch . '/files/alerts.json'), true);
        $stamp = $version['generated_at'] ?? null;
        if (!is_string($stamp) || ($manifest['generated_at'] ?? null) !== $stamp ||
            ($alerts['generated_at'] ?? null) !== $stamp ||
            ($manifest['result_count'] ?? null) !== 137 ||
            !is_array($manifest['results'] ?? null) || count($manifest['results']) !== 137) {
            throw new RuntimeException('invalid_metadata');
        }
        $allowed = [];
        foreach ($manifest['results'] as $item) {
            $p = $item['path'] ?? null;
            if (!is_string($p) || !preg_match('#^[a-z]{2}/[a-z0-9-]+\\.json$#D', $p) || isset($allowed[$p])) {
                throw new RuntimeException('invalid_manifest');
            }
            $allowed[$p] = true;
        }
        foreach ($paths as $p) {
            if (!is_string($p) || (!isset($allowed[$p]) && !in_array($p, ['version.json','manifest.json','alerts.json'], true))) {
                throw new RuntimeException('unexpected_target');
            }
            if (!is_file($batch . '/files/' . $p) || is_link($batch . '/files/' . $p)) {
                throw new RuntimeException('missing_staged_file');
            }
        }
        $snapshot = hash('sha256', $id . "\n" . $stamp);
        $target = $root . '/releases/' . $snapshot;
        if (is_dir($target)) return ['status'=>'snapshot_ready','snapshot_id'=>$snapshot,'mode'=>'sandbox'];
        $temp = $root . '/.build-' . bin2hex(random_bytes(8));
        if (!mkdir($temp, 0700)) throw new RuntimeException('storage_failed');
        try {
            $priorId = trim((string)@file_get_contents($root . '/current'));
            $prior = preg_match('/^[a-f0-9]{64}$/D', $priorId) ? $root . '/releases/' . $priorId : '';
            $updated = array_flip($paths);
            $metadata = ['version.json'=>true,'manifest.json'=>true,'alerts.json'=>true];
            foreach ($allowed as $p => $_) {
                $source = isset($updated[$p]) ? $batch . '/files/' . $p : $prior . '/' . $p;
                if (!is_file($source) || is_link($source)) throw new RuntimeException('missing_baseline');
                $dest = $temp . '/' . $p;
                if (!is_dir(dirname($dest)) && !mkdir(dirname($dest), 0700, true)) throw new RuntimeException('storage_failed');
                if (!copy($source, $dest)) throw new RuntimeException('copy_failed');
                $payload = json_decode((string)file_get_contents($dest), true);
                if (!is_array($payload)) throw new RuntimeException('invalid_result_json');
            }
            foreach (array_keys($metadata) as $p) {
                if (!copy($batch . '/files/' . $p, $temp . '/' . $p)) throw new RuntimeException('copy_failed');
            }
            if (!is_dir(dirname($target)) && !mkdir(dirname($target), 0700, true)) throw new RuntimeException('storage_failed');
            if (!rename($temp, $target)) throw new RuntimeException('promotion_failed');
        } finally {
            if (is_dir($temp)) {
                // Nothing is promoted from a partial tree. Cleanup is intentionally deferred.
            }
        }
        return ['status'=>'snapshot_ready','snapshot_id'=>$snapshot,'mode'=>'sandbox','files'=>count($allowed) + 3];
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}
