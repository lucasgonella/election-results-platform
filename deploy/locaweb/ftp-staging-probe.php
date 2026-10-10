<?php
declare(strict_types=1);
// TEST TOOL ONLY. Not included in any application artifact or production deploy.
// Install only inside a separately authorized ftp-staging-* fixture namespace.
ini_set('display_errors', '0');
header('Content-Type: application/json');
header('Cache-Control: no-store');
try {
    $root = realpath(dirname(__DIR__));
    if (!$root || !str_starts_with(basename($root), 'ftp-staging-')) throw new RuntimeException('fixture_namespace_required');
    $cfg = json_decode((string)file_get_contents($root . '/private/staging-config.json'), true, 32, JSON_THROW_ON_ERROR);
    if (($cfg['fixture_only'] ?? false) !== true || ($cfg['environment'] ?? '') !== 'fixture' || realpath($cfg['root'] ?? '') !== $root) throw new RuntimeException('fixture_configuration_required');
    require $root . '/private/ftp-publication.php';
    if (PHP_SAPI === 'cli') {
        $action = $argv[1] ?? 'runtime';
    } else {
        if (($_SERVER['HTTPS'] ?? '') !== 'on' || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') throw new RuntimeException('https_post_required');
        $raw = file_get_contents('php://input', false, null, 0, 1025);
        $ts = $_SERVER['HTTP_X_TIMESTAMP'] ?? '';
        $sig = $_SERVER['HTTP_X_SIGNATURE'] ?? '';
        if ($raw === false || strlen($raw) > 1024 || !preg_match('/^[0-9]{10}$/D', $ts) || abs(time()-(int)$ts)>30 || !hash_equals(hash_hmac('sha256', $ts . "\n" . $raw, hex2bin($cfg['fixture_key'])), $sig)) throw new RuntimeException('invalid_fixture_auth');
        $request = json_decode($raw, true, 8, JSON_THROW_ON_ERROR);
        if (array_keys($request) !== ['action']) throw new RuntimeException('invalid_request');
        $action = $request['action'];
    }
    // Reads can observe nodes; mutations must stay on the explicitly pinned host.
    // This does not certify NFS/multi-host locking or provider confinement.
    if (in_array($action, ['lock', 'replace_a', 'replace_b'], true)) {
        if (!is_string($cfg['activation_host'] ?? null) || $cfg['activation_host'] === '') throw new RuntimeException('unverified_lock_scope');
        if ($cfg['activation_host'] !== gethostname()) throw new RuntimeException('activation_host_mismatch');
    }
    $value = ['host'=>gethostname(), 'pid'=>getmypid(), 'sapi'=>PHP_SAPI, 'php'=>PHP_VERSION, 'probe_version'=>1];
    if ($action === 'runtime') {
        $value += ['effective_uid'=>function_exists('posix_geteuid') ? posix_geteuid() : null,
                   'effective_gid'=>function_exists('posix_getegid') ? posix_getegid() : null,
                   'fixture_root'=>$root, 'process_root'=>@readlink('/proc/self/root') ?: null,
                   'flock'=>function_exists('flock'),'fsync'=>function_exists('fsync'),'rename'=>function_exists('rename'),
                   'opcache'=>ini_get('opcache.enable'),'validate_timestamps'=>ini_get('opcache.validate_timestamps'),
                   'revalidate_freq'=>ini_get('opcache.revalidate_freq')];
    } elseif ($action === 'lock') {
        $handle = fopen($root . '/private/probe.lock', 'c');
        if (!$handle || !flock($handle, LOCK_EX | LOCK_NB)) throw new RuntimeException('publication_busy');
        usleep(2000000); // A bounded overlap window for two independent clients.
        flock($handle, LOCK_UN); fclose($handle);
        $value['status'] = 'lock_acquired';
    } elseif ($action === 'replace_a' || $action === 'replace_b') {
        fp_write($root . '/public/probe-marker.json', ['fixture'=>$action]);
        $value['status'] = 'replaced';
    } elseif ($action === 'read') {
        $value['marker'] = fp_json($root . '/public/probe-marker.json');
    } else throw new RuntimeException('invalid_action');
    echo json_encode($value, JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    http_response_code(409);
    $safe = $error instanceof RuntimeException && preg_match('/^[a-z_]+$/D', $error->getMessage()) ? $error->getMessage() : 'probe_failed';
    echo json_encode(['error'=>$safe]);
    if (PHP_SAPI === 'cli') exit(1);
}
