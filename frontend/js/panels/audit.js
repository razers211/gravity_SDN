const AuditPanel = {
    async init() {
        document.getElementById('panel-audit').innerHTML = `
            <div class="card">
                <div class="card-header"><h3>Configuration Audit Log</h3></div>
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>Time</th><th>Device</th><th>Action</th><th>Status</th></tr></thead>
                        <tbody><tr><td colspan="4" class="empty-state">No audits recorded yet.</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }
};
