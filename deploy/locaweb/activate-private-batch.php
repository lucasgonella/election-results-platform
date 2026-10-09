<?php
declare(strict_types=1);

/**
 * Authenticated API helper for PRIVATE test activation only.
 * Never writes under public_html/data. Call under the API's HMAC guard.
 */
function activatePrivateBatch(string $private, string $id): array {
    if (!preg_match('/^[a-f0-9]{32}$/D', $id)) {
        throw new RuntimeException('invalid_batch_id');
    }
    $root = $private . '/batches/' . $id;
    $info = json_decode((string)@file_get_contents($root . '/batch.json'), true);
    $paths = $info['paths'] ?? null;
    if (!is_array($paths) || count($paths) < 4 || count($paths) > 140 ||
        count(array_unique($paths)) !== count($paths)) {
        throw new RuntimeException('invalid_batch');
    }
    $required = ['version.json', 'manifest.json', 'alerts.json'];
    foreach ($required as $path) {
        if (!in_array($path, $paths, true)) throw new RuntimeException('incomplete_batch');
    }
    $files = $root . '/files';
    $data = [];
    $hashes = [];
    foreach ($paths as $path) {
        if (!is_string($path) || !preg_match(
            '#^(?:[a-z]{2}/[a-z0-9-]+\.json|manifest\.json|version\.json|alerts\.json)$#D', $path
        )) throw new RuntimeException('invalid_path');
        $file = $files . '/' . $path;
        if (!is_file($file) || is_link($file)) throw new RuntimeException('incomplete_batch');
        $raw = @file_get_contents($file);
        if ($raw === false || strlen($raw) > 6291456) throw new RuntimeException('invalid_file');
        try { $parsed = json_decode($raw, true, 512, JSON_THROW_ON_ERROR); }
        catch (JsonException $e) { throw new RuntimeException('invalid_json'); }
        if (!is_array($parsed)) throw new RuntimeException('invalid_json');
        $data[$path] = $parsed;
        $hashes[$path] = hash('sha256', $raw);
    }
    $m = $data['manifest.json'];
    $v = $data['version.json'];
    $a = $data['alerts.json'];
    $generated = $v['generated_at'] ?? null;
    if (!is_string($generated) || strlen($generated) < 10 ||
        ($m['generated_at'] ?? null) !== $generated ||
        ($a['generated_at'] ?? null) !== $generated ||
        ($m['result_count'] ?? null) !== 137 ||
        !is_array($m['results'] ?? null) ||
        count($m['results']) !== 137) throw new RuntimeException('invalid_metadata');
    try { $newTime = new DateTimeImmutable($generated); }
    catch (Exception $e) { throw new RuntimeException('invalid_timestamp'); }
    $allowed = [];
    foreach ($m['results'] as $entry) {
        $name = $entry['path'] ?? null;
        if (!is_string($name) || !preg_match('#^[a-z]{2}/[a-z0-9-]+\.json$#D', $name) ||
            isset($allowed[$name])) throw new RuntimeException('invalid_manifest');
        $allowed[$name] = true;
    }
    foreach ($paths as $path) {
        if (!in_array($path, $required, true) && !isset($allowed[$path])) {
            throw new RuntimeException('unexpected_target');
        }
    }
    $test = $private . '/test-public';
    if (!is_dir($test) && !@mkdir($test, 0700, true)) throw new RuntimeException('storage_failed');
    $fh = @fopen($private . '/private-activation.lock', 'c');
    if ($fh === false || !flock($fh, LOCK_EX | LOCK_NB)) throw new RuntimeException('activation_busy');
    try {
        $active = $test . '/version.json';
        if (is_file($active)) {
            $prior = json_decode((string)file_get_contents($active), true);
            $oldStamp = $prior['generated_at'] ?? '';
            if ($oldStamp === $generated) {
                return ['status' => 'already_activated', 'batch_id' => $id, 'mode' => 'sandbox'];
            }
            try { $oldTime = new DateTimeImmutable((string)$oldStamp); }
            catch (Exception $e) { throw new RuntimeException('invalid_current_version'); }
            if ($newTime <= $oldTime) throw new RuntimeException('stale_version');
        }
        // One-file-at-a-time atomic rename; version marker is LAST.
        // This deliberately does not claim multi-file transactional publication.
        $ordered = array_values(array_filter($paths, fn($p) => $p !== 'version.json'));
        $ordered[] = 'version.json';
        foreach ($ordered as $path) {
            if (!hash_equals($hashes[$path], hash_file('sha256', $files . '/' . $path))) {
                throw new RuntimeException('changed_staging_file');
            }
            $destination = $test . '/' . $path;
            $parent = dirname($destination);
            if (!is_dir($parent) && !@mkdir($parent, 0700, true)) throw new RuntimeException('storage_failed');
            $temp = @tempnam($parent, '.next-');
            if ($temp === false) throw new RuntimeException('storage_failed');
            if (!@copy($files . '/' . $path, $temp)) { @unlink($temp); throw new RuntimeException('copy_failed'); }
            @chmod($temp, 0600);
            if (!@rename($temp, $destination)) { @unlink($temp); throw new RuntimeException('rename_failed'); }
        }
        return ['status'=>'activated', 'batch_id'=>$id, 'mode'=>'sandbox',
                'files'=>count($paths), 'generated_at'=>$generated];
    } finally {
        flock($fh, LOCK_UN);
        fclose($fh);
    }
}
