<?php
declare(strict_types=1);
require_once __DIR__ . '/ftp-publication.php';

/** Pure plan preparation: no writes, activation or alteration of the legacy release. */
function fp_baseline_plan(array $cfg, string $state): array {
    $markerRaw = fp_read($cfg['site'], 'version.json');
    $marker = json_decode($markerRaw, true, 64, JSON_THROW_ON_ERROR);
    $id = $marker['snapshot_id'] ?? '';
    if (!preg_match('/^[a-f0-9]{64}$/D', $id)) fp_fail('invalid_baseline');
    $release = $cfg['site'] . '/releases/' . $id;
    if (is_link($release)) fp_fail('invalid_baseline');
    $stateHashes = [];
    foreach (['manifest.json','version.json','alerts.json','target-state.json','state-meta.json'] as $path)
        $stateHashes[$path] = hash('sha256', fp_read($state, $path));
    $inventory = [];
    foreach (array_merge(array_keys(fp_paths()), ['manifest.json','version.json','alerts.json']) as $path)
        $inventory[$path] = hash('sha256', fp_read($release, $path));
    $watermarks = fp_validate_release($release, $cfg);
    $releaseVersion = fp_json($release . '/version.json');
    if (($marker['environment'] ?? null) !== $releaseVersion['environment'] || ($marker['generated_at'] ?? null) !== $releaseVersion['generated_at']) fp_fail('invalid_baseline');
    $manifest = fp_json($release . '/manifest.json');
    $stateManifest = fp_json($state . '/manifest.json');
    $stateVersion = fp_json($state . '/version.json');
    if (($stateVersion['environment'] ?? null) !== $cfg['environment'] || ($stateManifest['environment'] ?? null) !== $cfg['environment']) fp_fail('state_mismatch');
    $entries = [];
    foreach ($stateManifest['results'] ?? [] as $entry) {
        $path = $entry['path'] ?? '';
        if (isset($entries[$path]) || !isset(fp_paths()[$path])) fp_fail('state_mismatch');
        ksort($entry); $entries[$path] = $entry;
    }
    if (count($entries) !== 137) fp_fail('state_mismatch');
    foreach ($manifest['results'] as $entry) {
        $path = $entry['path']; ksort($entry);
        if ($entry !== ($entries[$path] ?? null)) fp_fail('state_mismatch');
    }
    $targets = [];
    foreach (fp_json($state . '/target-state.json') as $target) {
        $path = $target['path'] ?? '';
        if (!isset($entries[$path]) || isset($targets[$path]) || ($target['tse_idg'] ?? null) !== $entries[$path]['tse_idg']) fp_fail('state_mismatch');
        $targets[$path] = true;
    }
    if (count($targets) !== 137) fp_fail('state_mismatch');
    if ((fp_json($state . '/alerts.json')['alerts'] ?? null) !== (fp_json($release . '/alerts.json')['alerts'] ?? null)) fp_fail('state_alerts_mismatch');
    // Keep metadata generation times as provenance, not as source watermarks.
    if (!hash_equals(hash('sha256', $markerRaw), hash('sha256', fp_read($cfg['site'], 'version.json')))) fp_fail('baseline_changed');
    foreach ($stateHashes as $path=>$hash) if (!hash_equals($hash, hash('sha256', fp_read($state, $path)))) fp_fail('state_changed');
    foreach ($inventory as $path=>$hash) if (!hash_equals($hash, hash('sha256', fp_read($release, $path)))) fp_fail('baseline_changed');
    return ['schema_version'=>1, 'snapshot_id'=>$id, 'marker_sha256'=>hash('sha256', $markerRaw),
        'inventory'=>$inventory, 'watermarks'=>$watermarks, 'state_hashes'=>$stateHashes];
}

/** Emit a reviewed plan in a NEW local output directory; never install it here. */
function fp_emit_baseline_plan(array $plan, string $key, string $output): void {
    if (file_exists($output) || !mkdir($output, 0700, true)) fp_fail('output_exists');
    fp_write($output . '/plan.json', $plan);
    $raw = fp_read($output, 'plan.json');
    if (file_put_contents($output . '/plan.sig', hash_hmac('sha256', $raw, $key)) !== 64) fp_fail('storage_error');
    fp_write($output . '/inventory.json', $plan['inventory']);
    $raw = fp_read($output, 'inventory.json');
    if (file_put_contents($output . '/inventory.sig', hash_hmac('sha256', $raw, $key)) !== 64) fp_fail('storage_error');
    fp_write($output . '/watermarks.json', $plan['watermarks']);
}

if (PHP_SAPI === 'cli' && realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    try {
        if ($argc !== 5) fp_fail('usage_config_state_keyfile_new_output');
        $cfg = fp_json($argv[1]);
        $keyHex = trim((string)file_get_contents($argv[3]));
        if (!preg_match('/^[a-f0-9]{64}$/D', $keyHex)) fp_fail('invalid_key');
        $plan = fp_baseline_plan($cfg, $argv[2]);
        fp_emit_baseline_plan($plan, hex2bin($keyHex), $argv[4]);
        echo json_encode(['status'=>'plan_prepared','snapshot_id'=>$plan['snapshot_id']]);
    } catch (Throwable $error) { fwrite(STDERR, "baseline_plan_failed\n"); exit(1); }
}
