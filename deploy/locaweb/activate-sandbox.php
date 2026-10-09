<?php
declare(strict_types=1);

/**
 * CLI-only integration harness for delta activation.
 * Intentionally CANNOT publish to public_html/data.
 *
 * Usage: php activate-sandbox.php <32-hex-batch-id>
 * Requires staged batch under ~/.election-publisher/batches.
 */
if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
function fail(string $message): never { fwrite(STDERR, "ERROR: $message\n"); exit(1); }
function safePath(string $path): bool {
    return strlen($path) <= 120 &&
        preg_match('#^(?:[a-z]{2}/[a-z0-9-]+\.json|manifest\.json|version\.json|alerts\.json)$#D', $path) === 1;
}
function readJson(string $path): array {
    $raw = @file_get_contents($path);
    if ($raw === false) fail("cannot read file: $path");
    try {
        $decoded = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException $e) { fail("invalid JSON: $path"); }
    if (!is_array($decoded)) fail("expected JSON object: $path");
    return $decoded;
}
function putAtomic(string $source, string $destination): void {
    $dir = dirname($destination);
    if (!is_dir($dir) && !mkdir($dir, 0700, true)) fail('cannot create destination');
    $tmp = tempnam($dir, '.next-');
    if ($tmp === false) fail('cannot create temp file');
    if (!copy($source, $tmp)) { @unlink($tmp); fail('copy failed'); }
    chmod($tmp, 0600);
    if (!rename($tmp, $destination)) { @unlink($tmp); fail('rename failed'); }
}
$id = $argv[1] ?? '';
if (!preg_match('/^[a-f0-9]{32}$/D', $id)) fail('invalid batch id');
$base = dirname(__DIR__, 3); // deployed path must be changed? see below
// Prefer HOME in CLI, not a guessed relative path.
$home = getenv('HOME') ?: '';
if ($home === '') fail('HOME not set');
$private = $home . '/.election-publisher';
$batch = $private . '/batches/' . $id;
$stage = $batch . '/files';
$meta = readJson($batch . '/batch.json');
$paths = $meta['paths'] ?? null;
if (!is_array($paths) || count($paths) < 4 || count($paths) > 140 ||
    count(array_unique($paths)) !== count($paths)) fail('invalid batch paths');
$required = ['manifest.json', 'alerts.json', 'version.json'];
foreach ($required as $p) if (!in_array($p, $paths, true)) fail('missing metadata');
foreach ($paths as $p) {
    if (!is_string($p) || !safePath($p) || !is_file($stage . '/' . $p) ||
        is_link($stage . '/' . $p)) fail('missing, invalid or linked path');
    readJson($stage . '/' . $p);
}
$manifest = readJson($stage . '/manifest.json');
$alerts = readJson($stage . '/alerts.json');
$version = readJson($stage . '/version.json');
if (($manifest['result_count'] ?? null) !== 137 ||
    !is_array($manifest['results'] ?? null) ||
    count($manifest['results']) !== 137) fail('manifest count mismatch');
$allowed = [];
foreach ($manifest['results'] as $item) {
    $p = $item['path'] ?? null;
    if (!is_string($p) || !safePath($p) || isset($allowed[$p])) fail('invalid manifest path');
    $allowed[$p] = true;
}
foreach ($paths as $p) {
    if (!in_array($p, $required, true) && !isset($allowed[$p])) fail('unexpected data path');
}
$generated = $version['generated_at'] ?? '';
if (!is_string($generated) || $generated === '' ||
    ($manifest['generated_at'] ?? null) !== $generated ||
    ($alerts['generated_at'] ?? null) !== $generated) fail('timestamp mismatch');
try {
    $stamp = new DateTimeImmutable($generated);
    $newTime = $stamp->format('U.u');
} catch (Exception $e) { fail('invalid timestamp'); }

// Never use production directories. All writes are confined to the private tree.
$target = $private . '/test-public';
if (!is_dir($target) && !mkdir($target, 0700, true)) fail('cannot create sandbox');
$lock = fopen($private . '/activation-sandbox.lock', 'c');
if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) fail('activation busy');
$activeVersion = $target . '/version.json';
if (is_file($activeVersion)) {
    $prev = readJson($activeVersion);
    $old = $prev['generated_at'] ?? null;
    if ($old === $generated) {
        echo json_encode(['status'=>'already_activated', 'batch_id'=>$id, 'mode'=>'sandbox']) . "\n";
        exit(0);
    }
    try { $oldTime = (new DateTimeImmutable((string)$old))->format('U.u'); }
    catch (Exception $e) { fail('invalid previous timestamp'); }
    if ((float)$newTime <= (float)$oldTime) fail('stale version');
}
foreach ($paths as $p) {
    if ($p === 'version.json') continue;
    putAtomic($stage . '/' . $p, $target . '/' . $p);
}
// Version marker is the final destination write. Readers should re-fetch it
// after data, but this does not constitute cross-file atomicity.
putAtomic($stage . '/version.json', $activeVersion);
echo json_encode(['status'=>'activated', 'batch_id'=>$id, 'mode'=>'sandbox',
                  'files'=>count($paths), 'generated_at'=>$generated]) . "\n";
