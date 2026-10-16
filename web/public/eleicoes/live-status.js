/* Public operational timestamps, separate from official generation and rendering. */
(function (root) {
    'use strict';
    if (!root.document || new URLSearchParams(root.location.search).get('turno') !== '2') return;
    const doc = root.document, panel = doc.getElementById('live-pipeline-status');
    if (!panel || !root.LiveData) return;
    panel.hidden = false;
    const labels = {awaiting_results: 'Aguardando apuração', current: 'Dados atualizados', updating: 'Atualizando',
        retrying: 'Tentando nova consulta', collection_late: 'Consulta ao TSE atrasada',
        collection_unavailable: 'Consulta ao TSE indisponível', publication_unavailable: 'Publicação indisponível',
        publication_late: 'Publicação atrasada',
        publication_failed: 'Falha na publicação', collector_failed: 'Falha na consulta oficial',
        review_required: 'Atualização em revisão',
        checkpoint_publication_inconsistency: 'Publicação em verificação', recovery_required: 'Atualização em recuperação',
        unknown_transaction: 'Publicação em verificação', collector_timer_inactive: 'Atualização interrompida',
        storage_warning: 'Atualização requer atenção', ftp_unavailable: 'Publicação temporariamente indisponível'};
    const display = stamp => stamp ? new Date(stamp).toLocaleString('pt-BR', {timeZone: 'America/Sao_Paulo'}) : 'Ainda não registrada';
    const metrics = root.ElectionLiveMetrics = {renderedAt: null, snapshotId: null,
        detectionAfterActivationSeconds: null, renderAfterDetectionSeconds: null};
    let status = null, busy = false;
    function render() {
        const context = root.ElectionPortal?.getContext();
        const generation = context?.result?.snapshot?.generated_at;
        const dataAge = generation ? (Date.now() - Date.parse(generation)) / 1000 : NaN;
        metrics.displayedDataAgeSeconds = Number.isFinite(dataAge) && dataAge >= 0 ? dataAge : null;
        let label = 'Verificando atualização';
        if (status) {
            label = labels[status.state] || 'Atualização em verificação';
            const sourceAge = status.last_source_success_at ? (Date.now() - Date.parse(status.last_source_success_at)) / 1000 : null;
            if (Date.now() - Date.parse(status.checked_at) > 180000) label = 'Status de atualização indisponível';
            else if (sourceAge !== null && sourceAge > status.source_stale_after_seconds) label = 'Consulta ao TSE atrasada';
            else if (context?.version?.snapshot_id && status.snapshot_id !== context.version.snapshot_id) label = 'Sincronizando publicação';
        }
        doc.getElementById('live-status-label').textContent = label;
        for (const [id, key] of [['live-source-at', 'last_source_success_at'], ['live-change-at', 'last_official_change_at'], ['live-publication-at', 'last_publication_at']]) {
            doc.getElementById(id).textContent = display(status?.[key]);
        }
        doc.getElementById('live-data-at').textContent = display(context?.result?.snapshot?.generated_at);
        if (status && metrics.snapshotId === status.snapshot_id && root.LiveData.stats.markerSnapshotId === metrics.snapshotId) {
            const delay = (Date.parse(root.LiveData.stats.markerDetectedAt) - Date.parse(status.last_activation_at || status.last_publication_at)) / 1000;
            metrics.detectionAfterActivationSeconds = Number.isFinite(delay) && delay >= 0 ? delay : null;
            const rendered = (Date.parse(metrics.renderedAt) - Date.parse(root.LiveData.stats.markerDetectedAt)) / 1000;
            metrics.renderAfterDetectionSeconds = Number.isFinite(rendered) && rendered >= 0 ? rendered : null;
        }
    }
    async function refresh() {
        if (busy || doc.hidden || root.LiveData.paused()) return;
        busy = true;
        try {
            const response = await root.LiveData.fetch('/data/turnos/2/status.json');
            if (!response.ok) throw new Error('status_unavailable');
            const next = await response.json();
            if (next.schema_version !== 1 || next.round !== 2 || next.environment !== 'oficial' || !Number.isFinite(Date.parse(next.checked_at))) throw new Error('invalid_public_status');
            status = next; root.LiveData.setState(next.election_state); render();
        } catch (_) {
            if (!status) doc.getElementById('live-status-label').textContent = 'Status de atualização indisponível';
            else render();
        } finally { busy = false; }
    }
    doc.addEventListener('election:context', event => {
        const id = event.detail?.version?.snapshot_id;
        if (id && metrics.snapshotId !== id) { metrics.snapshotId = id; metrics.renderedAt = new Date().toISOString(); }
        render();
    });
    doc.addEventListener('visibilitychange', () => { if (!doc.hidden) refresh(); });
    root.setInterval(refresh, 15000);
    root.setInterval(() => { if (!doc.hidden) render(); }, 1000);
    root.ElectionLiveStatus = {refresh};
    refresh();
})(window);
