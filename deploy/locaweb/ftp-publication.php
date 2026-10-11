<?php
declare(strict_types=1);
const FTP_PUBLICATION_HELPER_VERSION = 3;

/** Fixed-path result activator. No code uploads, destination inputs or shell calls. */
function fp_fail(string $code): never { throw new RuntimeException($code); }
function fp_assert_runtime(array $cfg): void {
    // NFS local locks cannot coordinate multiple hosts. Pin the control runtime
    // before any nonce/lock/state write; provider topology still needs validation.
    if (!isset($cfg['activation_host']) || !is_string($cfg['activation_host']) || $cfg['activation_host'] === '') fp_fail('unverified_lock_scope');
    if (!hash_equals($cfg['activation_host'], (string)gethostname())) fp_fail('activation_host_mismatch');
}
function fp_json(string $path): array {
    $value = json_decode((string)file_get_contents($path), true, 64, JSON_THROW_ON_ERROR);
    if (!is_array($value)) fp_fail('invalid_json');
    return $value;
}
function fp_sync_directory(string $path): void {
    // A file fsync does not persist its name. Unsupported barriers fail closed;
    // success still depends on the provider honoring NFS stable-storage semantics.
    if (!function_exists('fsync') || is_link($path) || !is_dir($path)) fp_fail('storage_error');
    $stream = @fopen($path, 'r');
    if ($stream === false) fp_fail('storage_error');
    try {
        try { $synced = @fsync($stream); } catch (Throwable) { $synced = false; }
        if (!$synced) fp_fail('storage_error');
    } finally { fclose($stream); }
}
function fp_write_bytes(string $path, string $raw): void {
    if (!function_exists('fsync') || is_link($path)) fp_fail('storage_error');
    $tmp = $path . '.' . bin2hex(random_bytes(8)) . '.tmp';
    $stream = fopen($tmp, 'x');
    if ($stream === false) fp_fail('storage_error');
    try {
        try {
            if (fwrite($stream, $raw) !== strlen($raw) || !fflush($stream)) fp_fail('storage_error');
            if (!fsync($stream)) fp_fail('storage_error');
        } finally { fclose($stream); }
        if (!rename($tmp, $path)) fp_fail('storage_error');
        fp_sync_directory(dirname($path));
    } finally {
        // Only the exclusively created temporary file; never unlink the target.
        if (is_file($tmp)) unlink($tmp);
    }
}
function fp_write(string $path, array $value): void {
    fp_write_bytes($path, json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES));
}
function fp_paths(): array {
    $ufs = explode(' ', 'ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to');
    $paths = [];
    foreach (array_merge($ufs, ['br', 'zz']) as $uf) $paths[$uf . '/president.json'] = [$uf, 1];
    foreach ($ufs as $uf) {
        foreach ([3=>'governor', 5=>'senator', 6=>'federal-deputy'] as $code=>$slug)
            $paths[$uf . '/' . $slug . '.json'] = [$uf, $code];
        $paths[$uf . '/' . ($uf === 'df' ? 'district-deputy' : 'state-deputy') . '.json'] = [$uf, $uf === 'df' ? 8 : 7];
    }
    return $paths;
}
function fp_read(string $root, string $path): string {
    $base = realpath($root);
    $full = realpath($root . '/' . $path);
    if (!$base || !$full || !str_starts_with($full, $base . DIRECTORY_SEPARATOR) || is_link($root . '/' . $path) || !is_file($full)) fp_fail('missing_file');
    if (filesize($full) > 16777216) fp_fail('file_too_large');
    $raw = file_get_contents($full);
    if ($raw === false) fp_fail('storage_error');
    return $raw;
}
function fp_inventory(string $release, string $key, ?string $adoptedRoot = null): array {
    $inventoryRoot = $release;
    if (!file_exists($release . '/inventory.json') && !file_exists($release . '/inventory.sig') && $adoptedRoot !== null) {
        $id = basename($release);
        if (!preg_match('/^[a-f0-9]{64}$/D', $id)) fp_fail('invalid_baseline');
        $inventoryRoot = $adoptedRoot . '/' . $id;
    }
    $raw = fp_read($inventoryRoot, 'inventory.json');
    $sig = trim(fp_read($inventoryRoot, 'inventory.sig'));
    if (!hash_equals(hash_hmac('sha256', $raw, $key), $sig)) fp_fail('corrupt_baseline');
    $inventory = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
    $expected = array_merge(array_keys(fp_paths()), ['manifest.json', 'version.json', 'alerts.json']);
    if (count($inventory) !== 140 || array_diff($expected, array_keys($inventory))) fp_fail('corrupt_baseline');
    foreach ($inventory as $path=>$hash) {
        if (!in_array($path, $expected, true) || !hash_equals($hash, hash('sha256', fp_read($release, $path)))) fp_fail('corrupt_baseline');
    }
    return $inventory;
}
function fp_marker(array $cfg): ?array {
    return is_file($cfg['site'] . '/version.json') ? fp_json($cfg['site'] . '/version.json') : null;
}
function fp_canonical_value(mixed $value): mixed {
    if (!is_array($value)) return $value;
    if (!array_is_list($value)) ksort($value);
    foreach ($value as $key=>$item) $value[$key] = fp_canonical_value($item);
    return $value;
}
function fp_source_fingerprint(array $payload): string {
    $snapshot = $payload['snapshot'];
    unset($snapshot['captured_at']);
    $snapshot['tse_idg'] = (string)$snapshot['tse_idg'];
    return hash('sha256', json_encode(fp_canonical_value([$snapshot, $payload['candidates'], $payload['office']]), JSON_THROW_ON_ERROR));
}
function fp_receipt(array $cfg, string $id): array {
    $marker = fp_marker($cfg);
    if ($marker === null) {
        $history = scandir($cfg['private'] . '/receipts');
        if ($history === false) fp_fail('storage_error');
        // Loss of the selection marker must not look like a fresh installation
        // or turn an historical receipt into confirmation of healthy publication.
        if (array_diff($history, ['.', '..'])) fp_fail('marker_missing_requires_review');
    }
    // Reconcile the visible commit point; require a successful directory barrier
    // before acknowledging a marker whose original fsync/response may have failed.
    if (($marker['delivery_id'] ?? '') === $id) {
        if (($marker['snapshot_id'] ?? '') !== $id) fp_fail('invalid_receipt');
        fp_inventory($cfg['site'] . '/releases/' . $marker['snapshot_id'], $cfg['key'], $cfg['private'] . '/adopted-baselines');
        fp_sync_directory($cfg['site']);
        return ['status'=>'published', 'delivery_id'=>$id, 'snapshot_id'=>$marker['snapshot_id']];
    }
    $path = $cfg['private'] . '/receipts/' . $id . '.json';
    if (is_file($path)) {
        $receipt = fp_json($path);
        if (count($receipt) !== 3 || ($receipt['status'] ?? '') !== 'published'
            || ($receipt['delivery_id'] ?? '') !== $id || ($receipt['snapshot_id'] ?? '') !== $id) fp_fail('invalid_receipt');
        fp_inventory($cfg['site'] . '/releases/' . $id, $cfg['key'], $cfg['private'] . '/adopted-baselines');
        fp_sync_directory(dirname($path));
        return $receipt;
    }
    return ['status'=>'unknown', 'delivery_id'=>$id];
}
function fp_watermarks(string $path, ?string $baseline): array {
    if (is_link($path)) fp_fail('watermarks_inconsistent_requires_review');
    if (!is_file($path)) {
        if ($baseline !== null) fp_fail('watermarks_missing_requires_review');
        return [];
    }
    $water = fp_json($path);
    $paths = array_keys(fp_paths());
    if (count($water) !== count($paths) || array_diff($paths, array_keys($water))) fp_fail('watermarks_inconsistent_requires_review');
    foreach ($water as $path=>$entry) {
        if (!is_array($entry) || !is_array($entry['identity'] ?? null) || !array_is_list($entry['identity'])
            || count($entry['identity']) !== 3 || !is_string($entry['identity'][0] ?? null)
            || !is_int($entry['identity'][1] ?? null) || !is_int($entry['identity'][2] ?? null)
            || !is_int($entry['time'] ?? null) || $entry['time'] < 1 || !is_string($entry['idg'] ?? null)
            || !preg_match('/^[0-9]{1,20}$/D', $entry['idg']) || !is_string($entry['fingerprint'] ?? null)
            || !preg_match('/^[a-f0-9]{64}$/D', $entry['fingerprint'])
            || !array_key_exists('totalization_final', $entry)
            || ($entry['totalization_final'] !== null && !is_bool($entry['totalization_final']))) fp_fail('watermarks_inconsistent_requires_review');
        if ($baseline !== null) {
            $payload = fp_json($baseline . '/' . $path);
            $snapshot = $payload['snapshot'];
            $time = strtotime($snapshot['generated_at']);
            $identity = [$payload['environment'], $payload['election']['code'], $payload['election']['round']];
            if ($entry['identity'] !== $identity || $entry['time'] < $time
                || ($entry['time'] === $time && ($entry['idg'] !== (string)$snapshot['tse_idg']
                    || $entry['fingerprint'] !== fp_source_fingerprint($payload)))
                || (($snapshot['totalization_final'] ?? null) === true && ($entry['totalization_final'] ?? null) !== true)) fp_fail('watermarks_inconsistent_requires_review');
        }
    }
    return $water;
}
function fp_run(array $cfg, string $action, string $id): array {
    fp_assert_runtime($cfg);
    if (!preg_match('/^[a-f0-9]{64}$/D', $id)) fp_fail('invalid_id');
    foreach (['private', 'inbox', 'site'] as $name) {
        if (!is_dir($cfg[$name]) || is_link($cfg[$name])) fp_fail('invalid_configuration');
    }
    $private = realpath($cfg['private']); $inbox = realpath($cfg['inbox']); $site = realpath($cfg['site']);
    $publicRoot = realpath($cfg['public_root']);
    if (!$publicRoot || str_starts_with($private . DIRECTORY_SEPARATOR, $publicRoot . DIRECTORY_SEPARATOR) || str_starts_with($inbox . DIRECTORY_SEPARATOR, $publicRoot . DIRECTORY_SEPARATOR) || $private === $inbox) fp_fail('private_storage_required');
    if ($site !== $publicRoot . DIRECTORY_SEPARATOR . 'data' || str_starts_with($private . DIRECTORY_SEPARATOR, $inbox . DIRECTORY_SEPARATOR) || str_starts_with($inbox . DIRECTORY_SEPARATOR, $private . DIRECTORY_SEPARATOR)) fp_fail('invalid_configuration');
    $lock = fopen($private . '/activation.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) fp_fail('publication_busy');
    $legacyLock = null;
    try {
        if (isset($cfg['legacy_lock'])) {
            if (is_link($cfg['legacy_lock'])) fp_fail('invalid_configuration');
            $legacyLock = fopen($cfg['legacy_lock'], 'c');
            if (!$legacyLock || !flock($legacyLock, LOCK_EX | LOCK_NB)) fp_fail('publication_busy');
        }
        foreach (['receipts', 'journals', 'sealed'] as $dir) if (!is_dir($private . '/' . $dir) && !mkdir($private . '/' . $dir, 0700)) fp_fail('storage_error');
        fp_sync_directory($private);
        if ($action === 'status') return fp_receipt($cfg, $id);
        if ($action === 'rollback') {
            $journalPath = $private . '/journals/' . $id . '.json';
            if (!is_file($journalPath)) fp_fail('rollback_unavailable');
            $journal = fp_json($journalPath);
            $current = fp_marker($cfg);
            if (($current['rollback_of'] ?? '') === $id) return ['status'=>'rolled_back', 'snapshot_id'=>$current['snapshot_id']];
            if (($current['delivery_id'] ?? '') !== $id || !is_array($journal['previous'])) fp_fail('rollback_conflict');
            fp_watermarks($private . '/watermarks.json', $site . '/releases/' . $current['snapshot_id']);
            $previous = $journal['previous'];
            fp_inventory($site . '/releases/' . $previous['snapshot_id'], $cfg['key'], $private . '/adopted-baselines');
            $previous['activation_revision'] = bin2hex(random_bytes(16));
            $previous['rollback_of'] = $id;
            fp_write($site . '/version.json', $previous);
            return ['status'=>'rolled_back', 'snapshot_id'=>$previous['snapshot_id']];
        }
        if ($action !== 'activate' || !($cfg['enabled'] ?? false)) fp_fail('activation_disabled');
        $known = fp_receipt($cfg, $id);
        if ($known['status'] === 'published') return $known;
        $source = $inbox . '/' . $id;
        $resolvedSource = realpath($source);
        if (is_link($source) || !$resolvedSource || dirname($resolvedSource) !== $inbox) fp_fail('invalid_delivery_path');
        if (trim(fp_read($source, 'READY')) !== $id) fp_fail('incomplete_delivery');
        $raw = fp_read($source, 'delivery.json');
        if (strlen($raw) > 65536 || !hash_equals($id, hash('sha256', $raw)) || !hash_equals(hash_hmac('sha256', $raw, $cfg['key']), trim(fp_read($source, 'delivery.sig')))) fp_fail('invalid_delivery_signature');
        $delivery = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
        if (($delivery['schema_version'] ?? null) !== 1 || !is_array($delivery['files'] ?? null)) fp_fail('invalid_descriptor');
        $files = $delivery['files'];
        $totalBytes = 0;
        $allowed = array_merge(array_keys(fp_paths()), ['manifest.json', 'version.json', 'alerts.json']);
        if (count($files) > 140 || array_diff(['manifest.json','version.json','alerts.json'], array_keys($files))) fp_fail('missing_metadata');
        $sealed = $private . '/sealed/' . $id;
        if (!is_dir($sealed) && !mkdir($sealed, 0700)) fp_fail('storage_error');
        foreach ($files as $path=>$entry) {
            if (!in_array($path, $allowed, true) || !is_array($entry) || !is_int($entry['size'] ?? null) || $entry['size'] < 1 || $entry['size'] > 16777216 || !preg_match('/^[a-f0-9]{64}$/D', $entry['sha256'] ?? '')) fp_fail('invalid_file');
            $totalBytes += $entry['size'];
            if ($totalBytes > 536870912) fp_fail('delivery_too_large');
            $bytes = fp_read($source . '/files', $path);
            if (strlen($bytes) !== $entry['size'] || !hash_equals($entry['sha256'], hash('sha256', $bytes))) fp_fail('hash_mismatch');
            $parent = dirname($sealed . '/' . $path);
            if (!is_dir($parent) && !mkdir($parent, 0700, true)) fp_fail('storage_error');
            fp_write_bytes($sealed . '/' . $path, $bytes);
        }
        $current = fp_marker($cfg);
        if (($delivery['base_snapshot_id'] ?? null) !== ($current['snapshot_id'] ?? null)) fp_fail('baseline_conflict');
        $baseline = null;
        if ($current !== null) {
            if (!preg_match('/^[a-f0-9]{64}$/D', $current['snapshot_id'] ?? '')) fp_fail('invalid_baseline');
            $baseline = $site . '/releases/' . $current['snapshot_id'];
            fp_inventory($baseline, $cfg['key'], $private . '/adopted-baselines');
        } elseif (array_diff($allowed, array_keys($files))) fp_fail('baseline_absent');
        $waterPath = $private . '/watermarks.json';
        $water = fp_watermarks($waterPath, $baseline);
        $release = $site . '/releases/' . $id;
        if (!is_dir($site . '/releases') && !mkdir($site . '/releases', 0755)) fp_fail('storage_error');
        // Build in a sibling temporary directory; abandoned builds are never publicly selected.
        $build = $site . '/releases/.build-' . bin2hex(random_bytes(16));
        if (!mkdir($build, 0755)) fp_fail('storage_error');
        $inventory = [];
        foreach ($allowed as $path) {
            $bytes = fp_read(isset($files[$path]) ? $sealed : (string)$baseline, $path);
            $parent = dirname($build . '/' . $path);
            if (!is_dir($parent) && !mkdir($parent, 0755, true)) fp_fail('storage_error');
            fp_write_bytes($build . '/' . $path, $bytes);
            $inventory[$path] = hash('sha256', $bytes);
        }
        $water = fp_validate_release($build, $cfg, $water);
        $version = fp_json($build . '/version.json');
        fp_write($build . '/inventory.json', $inventory);
        $inventoryRaw = (string)file_get_contents($build . '/inventory.json');
        fp_write_bytes($build . '/inventory.sig', hash_hmac('sha256', $inventoryRaw, $cfg['key']));
        fp_inventory($build, $cfg['key']);
        if (is_dir($release)) {
            if (fp_inventory($release, $cfg['key']) !== $inventory) fp_fail('release_conflict');
        } elseif (!rename($build, $release)) fp_fail('storage_error');
        fp_sync_directory($site . '/releases');
        fp_write($private . '/journals/' . $id . '.json', ['previous'=>$current, 'delivery_id'=>$id]);
        // Keep the watermark even on rollback. Conservative failure before activation is resumable.
        fp_write($waterPath, $water);
        if (($cfg['fault_before_activation'] ?? false)) fp_fail('injected_before_activation');
        $marker = array_merge($version, ['snapshot_id'=>$id, 'delivery_id'=>$id, 'activation_revision'=>bin2hex(random_bytes(16))]);
        fp_write($site . '/version.json', $marker);
        $receipt = ['status'=>'published', 'delivery_id'=>$id, 'snapshot_id'=>$id];
        fp_write($private . '/receipts/' . $id . '.json', $receipt);
        return $receipt;
    } finally {
        if (is_resource($legacyLock)) { flock($legacyLock, LOCK_UN); fclose($legacyLock); }
        flock($lock, LOCK_UN); fclose($lock);
    }
}

/** Shared read-only validation for normal publication and assisted adoption. */
function fp_validate_release(string $build, array $cfg, array $water = []): array {
        $manifest = fp_json($build . '/manifest.json');
        $version = fp_json($build . '/version.json');
        $alerts = fp_json($build . '/alerts.json');
        foreach ([$manifest, $alerts] as $meta) if (($meta['environment'] ?? null) !== ($version['environment'] ?? null) || ($meta['generated_at'] ?? null) !== ($version['generated_at'] ?? null)) fp_fail('metadata_mismatch');
        if (!is_string($version['environment'] ?? null) || !is_string($version['generated_at'] ?? null) || count($manifest['results'] ?? []) !== 137) fp_fail('invalid_manifest');
        if ($version['environment'] !== ($cfg['environment'] ?? null) || !in_array($cfg['round'] ?? null, [1,2], true)) fp_fail('unauthorized_environment');
        $entries = [];
        foreach ($manifest['results'] as $entry) {
            $path = $entry['path'] ?? '';
            if (!isset(fp_paths()[$path]) || isset($entries[$path])) fp_fail('invalid_manifest');
            $entries[$path] = $entry;
        }
        foreach (fp_paths() as $path=>[$scope, $office]) {
            $payload = fp_json($build . '/' . $path); $entry = $entries[$path];
            $snapshot = $payload['snapshot'] ?? [];
            $sourceId = $snapshot['tse_idg'] ?? null;
            if ((!is_int($sourceId) && !is_string($sourceId)) || !preg_match('/^[0-9]{1,20}$/D', (string)$sourceId)) fp_fail('invalid_source_id');
            $time = strtotime($snapshot['generated_at'] ?? '');
            if (!preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/D', $snapshot['generated_at'] ?? '')) fp_fail('invalid_source_time');
            if (($payload['schema_version'] ?? null) !== 1 || ($payload['environment'] ?? '') !== $version['environment'] || strtolower($payload['scope']['code'] ?? '') !== $scope || ($payload['office']['code'] ?? null) !== $office || ($entry['scope'] ?? '') !== $scope || ($entry['office'] ?? null) !== $office || ($entry['election_code'] ?? null) !== ($payload['election']['code'] ?? null) || ($entry['round'] ?? null) !== ($payload['election']['round'] ?? null) || ($entry['tse_idg'] ?? null) !== $sourceId || ($entry['captured_at'] ?? null) !== ($snapshot['captured_at'] ?? null) || !is_array($payload['candidates'] ?? null) || ($payload['candidate_count'] ?? null) !== count($payload['candidates']) || ($entry['candidate_count'] ?? null) !== count($payload['candidates']) || !$time) fp_fail('invalid_result');
            $identity = [$version['environment'], $payload['election']['code'], $payload['election']['round']];
            if (!is_int($identity[1]) || $identity[1] < 1 || $identity[2] !== $cfg['round']) fp_fail('unauthorized_election');
            $fingerprint = fp_source_fingerprint($payload);
            $old = $water[$path] ?? null;
            if ($old && ($old['totalization_final'] ?? null) === true && ($snapshot['totalization_final'] ?? null) !== true) fp_fail('totalization_reopened_requires_review');
            // Same source generation with changed content is ambiguous and fails closed.
            if ($old && ($old['identity'] !== $identity || $time < $old['time'] || ($time === $old['time'] && ($old['idg'] !== (string)$sourceId || $old['fingerprint'] !== $fingerprint)))) fp_fail('result_regression');
            $water[$path] = ['identity'=>$identity, 'time'=>$time, 'idg'=>(string)$sourceId, 'fingerprint'=>$fingerprint,
                'totalization_final'=>$snapshot['totalization_final'] ?? null];
        }
        return $water;
}
