/**
 * Alarm Center Panel
 * Displays real-time telemetry alarms and 1-3-5 troubleshooting.
 */

const AlarmsPanel = {
    async init() {
        this.container = document.getElementById('panel-alarms');
        this.renderSkeleton();
        await this.loadData();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>Alarm Center</h3>
                    <div class="header-actions">
                        <select class="filter-select" id="alarm-severity-filter">
                            <option value="all">All Severities</option>
                            <option value="5">Critical Only</option>
                            <option value="4">Major & Above</option>
                        </select>
                        <button class="btn btn-outline btn-sm" onclick="AlarmsPanel.loadData()"><span class="material-icons-outlined">refresh</span> Refresh</button>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table id="alarms-table">
                        <thead>
                            <tr>
                                <th>Severity</th>
                                <th>Title</th>
                                <th>Device</th>
                                <th>Source</th>
                                <th>Raised At</th>
                                <th>1-3-5 Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="7" class="empty-state">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        document.getElementById('alarm-severity-filter').addEventListener('change', () => this.filterAlarms());
    },

    async loadData() {
        const tbody = document.querySelector('#alarms-table tbody');
        try {
            this.alarms = await App.apiGet('/api/v1/telemetry/alarms?status=active');
            this.filterAlarms();
        } catch (error) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--danger)">Failed to load alarms</td></tr>';
        }
    },

    getSeveritySpan(severity) {
        if (severity >= 5) return '<span class="badge badge-danger">Critical</span>';
        if (severity === 4) return '<span class="badge" style="background:#ea580c; color:#fff;">Major</span>';
        if (severity === 3) return '<span class="badge badge-warning">Minor</span>';
        return '<span class="badge badge-info">Warning</span>';
    },

    get135Status(alarm) {
        if (alarm.severity < 4) return '<span class="text-muted">-</span>';
        
        let html = '<div style="display:flex; gap:4px;">';
        
        // 1m: Detected (always true if we have the alarm)
        html += '<div title="1m: Detected" style="width:12px; height:12px; border-radius:50%; background:var(--success);"></div>';
        
        // 3m: Located (Impact Analysis)
        const located = alarm.impacted_tenants && alarm.impacted_tenants.length > 0;
        html += `<div title="3m: Located" style="width:12px; height:12px; border-radius:50%; background:var(--${located?'success':'border'});"></div>`;
        
        // 5m: Rectified (Remediation)
        const rectified = alarm.remediation_status === 'success';
        const rectColor = rectified ? 'success' : (alarm.remediation_status === 'in-progress' ? 'warning' : 'border');
        html += `<div title="5m: Rectified" style="width:12px; height:12px; border-radius:50%; background:var(--${rectColor});"></div>`;
        
        html += '</div>';
        return html;
    },

    filterAlarms() {
        const filterVal = document.getElementById('alarm-severity-filter').value;
        const tbody = document.querySelector('#alarms-table tbody');
        
        let filtered = this.alarms || [];
        if (filterVal !== 'all') {
            const minSeverity = parseInt(filterVal);
            filtered = filtered.filter(a => a.severity >= minSeverity);
        }

        if (filtered.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="empty-state" style="padding: 40px 20px;">
                        <span class="material-icons-outlined" style="font-size:48px; color:var(--success);">check_circle</span>
                        <h4>No Active Alarms</h4>
                        <p>The network is operating normally.</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = filtered.map(a => `
            <tr>
                <td>${this.getSeveritySpan(a.severity)}</td>
                <td style="font-weight:500;">${a.title}</td>
                <td>${a.device_hostname}</td>
                <td>${a.source}</td>
                <td>${App.formatDate(a.raised_at)}</td>
                <td>${this.get135Status(a)}</td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="AlarmsPanel.viewTimeline('${a.id}')">View Timeline</button>
                    <button class="btn-icon" title="Acknowledge"><span class="material-icons-outlined">done</span></button>
                </td>
            </tr>
        `).join('');
    },

    async viewTimeline(alarmId) {
        const alarm = this.alarms.find(a => a.id === alarmId);
        if (!alarm) return;

        const isLocated = alarm.impacted_tenants && alarm.impacted_tenants.length > 0;
        const isRectified = alarm.remediation_status === 'success';

        const html = `
            <div style="margin-bottom:20px;">
                <strong>Device:</strong> ${alarm.device_hostname}<br>
                <strong>Interface:</strong> ${alarm.interface_name || 'N/A'}<br>
                <strong>Message:</strong> ${alarm.message || alarm.title}
            </div>

            <h4>Intelligent O&M 1-3-5 Timeline</h4>
            <div class="timeline" style="margin-top:16px;">
                
                <div class="timeline-item completed">
                    <div class="timeline-time">${App.formatDate(alarm.raised_at)}</div>
                    <div class="timeline-title">1 Minute: Anomaly Detected</div>
                    <div class="timeline-desc">Telemetry ingested via ${alarm.source}. Alarm generated.</div>
                </div>

                <div class="timeline-item ${isLocated ? 'completed' : 'active'}">
                    <div class="timeline-time">${isLocated ? 'Within 3 minutes' : 'In Progress...'}</div>
                    <div class="timeline-title">3 Minutes: Impact Location</div>
                    <div class="timeline-desc">
                        ${isLocated 
                            ? `Graph traversal complete. Impacted Tenants: ${alarm.impacted_tenants.join(', ')}` 
                            : 'Analyzing 5-layer digital map topology...'}
                    </div>
                </div>

                <div class="timeline-item ${isRectified ? 'completed' : (isLocated ? 'active' : '')}">
                    <div class="timeline-time">${isRectified ? 'Within 5 minutes' : 'Pending'}</div>
                    <div class="timeline-title">5 Minutes: Autonomous Remediation</div>
                    <div class="timeline-desc">
                        ${isRectified 
                            ? `Remediation successful: ${alarm.remediation_action}` 
                            : 'Awaiting SLA breach to trigger autonomous bypass path deployment.'}
                    </div>
                </div>

            </div>
        `;

        App.showModal(`Alarm: ${alarm.title}`, html);
    }
};
