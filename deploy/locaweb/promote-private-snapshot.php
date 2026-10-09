<?php
declare(strict_types=1);
/** Switch private snapshot pointer only; never publishes a public URL. */
function promotePrivateSnapshot(string $base, string $snapshotId, bool $rollback = false): array {
    if (!preg_match('/^[a-f0-9]{64}$/D', $snapshotId)) throw new RuntimeException('invalid_snapshot_id');
    $root = $base . '/snapshot-sandbox';
    $target = $root . '/releases/' . $snapshotId;
    if (!is_dir($target) || !is_file($target . '/version.json')) throw new RuntimeException('snapshot_not_found');
    $lock = @fopen($base . '/snapshot-build.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) throw new RuntimeException('snapshot_busy');
    try {
        $old = trim((string)@file_get_contents($root . '/current'));
        if ($old === $snapshotId) return ['status'=>'already_promoted','snapshot_id'=>$snapshotId,'mode'=>'sandbox'];
        if ($rollback && $snapshotId !== trim((string)@file_get_contents($root . '/previous'))) throw new RuntimeException('rollback_target_mismatch');
        $oldVersion = is_file($root.'/releases/'.$old.'/version.json') ? json_decode((string)file_get_contents($root.'/releases/'.$old.'/version.json'), true) : null;
        $newVersion = json_decode((string)file_get_contents($target.'/version.json'), true);
        if (!is_array($newVersion) || !is_string($newVersion['generated_at'] ?? null)) throw new RuntimeException('invalid_snapshot');
        if (!$rollback && is_array($oldVersion) && isset($oldVersion['generated_at']) &&
            strtotime((string)$newVersion['generated_at']) <= strtotime((string)$oldVersion['generated_at'])) throw new RuntimeException('stale_version');
        foreach (['manifest.json','alerts.json'] as $file) {
            $v = json_decode((string)@file_get_contents($target.'/'.$file), true);
            if (!is_array($v) || ($v['generated_at'] ?? null) !== $newVersion['generated_at']) throw new RuntimeException('inconsistent_snapshot');
        }
        $tmp = $root . '/.current-' . bin2hex(random_bytes(8));
        if (file_put_contents($tmp, $snapshotId . "\n") === false || !rename($tmp, $root.'/current')) throw new RuntimeException('pointer_write_failed');
        if (preg_match('/^[a-f0-9]{64}$/D', $old)) {
            $prevTmp = $root . '/.previous-' . bin2hex(random_bytes(8));
            if (file_put_contents($prevTmp, $old . "\n") === false || !rename($prevTmp, $root.'/previous')) throw new RuntimeException('previous_write_failed');
        }
        return ['status'=>$rollback?'rolled_back':'promoted','snapshot_id'=>$snapshotId,'mode'=>'sandbox'];
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}
