/**
 * Dashboard Panel
 * Displays global KPIs, health scores, and summary data.
 */

const DashboardPanel = {
    async init() {
        this.container = document.getElementById('panel-dashboard');
        this.renderSkeleton();
        await this.loadData();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="kpi-grid" id="dashboard-kpis">
                <!-- Skeletons -->
                <div class="kpi-card"><div class="kpi-content">Loading...</div></div>
                <div class="kpi-card"><div class="kpi-content">Loading...</div></div>
                <div class="kpi-card"><div class="kpi-content">Loading...</div></div>
                <div class="kpi-card"><div class="kpi-content">Loading...</div></div>
            </div>

            <div class="grid-2">
                <div class="card">
                    <div class="card-header">
                        <h3>Fabric Health Overview</h3>
                    </div>
                    <div class="card-body" style="display:flex; justify-content:center; align-items:center; height:250px;">
                        <div class="health-gauge">
                            <canvas id="health-chart"></canvas>
                            <div style="position:absolute; text-align:center;">
                                <div class="health-gauge-value" id="health-score">--</div>
                                <div class="health-gauge-label">Overall Score</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <h3>Active Alarms by Severity</h3>
                        <a href="#alarms" class="btn-text">View All</a>
                    </div>
                    <div class="card-body">
                        <canvas id="alarms-chart" height="210"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h3>Recent Operations Audit</h3>
                </div>
                <div class="table-wrapper">
                    <table id="recent-audit-table">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Device</th>
                                <th>Action</th>
                                <th>User</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody><tr><td colspan="5" style="text-align:center">Loading...</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    },

    async loadData() {
        try {
            // In a real scenario with our FastAPI backend, these endpoints exist.
            // Using Promise.allSettled to gracefully handle if some endpoints are empty/missing initially.
            const [devicesReq, alarmsReq, fabricsReq] = await Promise.allSettled([
                App.apiGet('/api/v1/devices'),
                App.apiGet('/api/v1/telemetry/alarms?status=active'),
                App.apiGet('/api/v1/fabrics')
            ]);

            const devices = devicesReq.status === 'fulfilled' ? devicesReq.value : [];
            const alarms = alarmsReq.status === 'fulfilled' ? alarmsReq.value : [];
            const fabrics = fabricsReq.status === 'fulfilled' ? fabricsReq.value : [];

            this.renderKPIs(devices, alarms, fabrics);
            this.renderHealthChart(); // Mock for now, requires health_evaluator endpoint integration
            this.renderAlarmsChart(alarms);
            await this.loadAuditLog();

        } catch (error) {
            console.error("Dashboard load failed:", error);
            App.showToast("Dashboard Error", "Failed to load dashboard data", "error");
        }
    },

    renderKPIs(devices, alarms, fabrics) {
        const offlineDevices = devices.filter(d => d.status !== 'active').length;
        const criticalAlarms = alarms.filter(a => a.severity >= 4).length;

        const kpisHtml = `
            <div class="kpi-card">
                <div class="kpi-icon blue"><span class="material-icons-outlined">dns</span></div>
                <div class="kpi-content">
                    <div class="kpi-value">${devices.length}</div>
                    <div class="kpi-label">Managed Devices</div>
                    <div class="kpi-trend ${offlineDevices > 0 ? 'down' : 'up'}">
                        ${offlineDevices} offline
                    </div>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-icon ${criticalAlarms > 0 ? 'red' : 'green'}"><span class="material-icons-outlined">notifications_active</span></div>
                <div class="kpi-content">
                    <div class="kpi-value">${alarms.length}</div>
                    <div class="kpi-label">Active Alarms</div>
                    <div class="kpi-trend ${criticalAlarms > 0 ? 'down' : 'up'}">
                        ${criticalAlarms} critical
                    </div>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-icon orange"><span class="material-icons-outlined">lan</span></div>
                <div class="kpi-content">
                    <div class="kpi-value">${fabrics.length}</div>
                    <div class="kpi-label">Managed Fabrics</div>
                    <div class="kpi-trend up">All stable</div>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-icon green"><span class="material-icons-outlined">rocket_launch</span></div>
                <div class="kpi-content">
                    <div class="kpi-value">0</div>
                    <div class="kpi-label">Provisioning Tasks</div>
                    <div class="kpi-trend">Last 24h</div>
                </div>
            </div>
        `;
        document.getElementById('dashboard-kpis').innerHTML = kpisHtml;
    },

    renderHealthChart() {
        const ctx = document.getElementById('health-chart').getContext('2d');
        const score = 98; // Would come from health evaluator
        document.getElementById('health-score').textContent = score;
        document.getElementById('health-score').style.color = score > 90 ? 'var(--success)' : 'var(--warning)';

        new Chart(ctx, {
            type: 'doughnut',
            data: {
                datasets: [{
                    data: [score, 100 - score],
                    backgroundColor: [score > 90 ? '#10b981' : '#f59e0b', '#f3f4f6'],
                    borderWidth: 0,
                    circumference: 270,
                    rotation: 225
                }]
            },
            options: {
                cutout: '80%',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { tooltip: { enabled: false }, legend: { display: false } }
            }
        });
    },

    renderAlarmsChart(alarms) {
        const ctx = document.getElementById('alarms-chart').getContext('2d');
        
        let critical = 0, major = 0, minor = 0, warning = 0;
        alarms.forEach(a => {
            if (a.severity === 5) critical++;
            else if (a.severity === 4) major++;
            else if (a.severity === 3) minor++;
            else warning++;
        });

        // If no alarms, show empty
        if (alarms.length === 0) {
            critical = 0; major = 0; minor = 1; // Fake to show empty pie
        }

        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Critical', 'Major', 'Minor', 'Warning'],
                datasets: [{
                    data: alarms.length ? [critical, major, minor, warning] : [0,0,0,1],
                    backgroundColor: alarms.length ? ['#dc2626', '#ea580c', '#d97706', '#f59e0b'] : ['#e5e7eb'],
                    borderWidth: 1
                }]
            },
            options: {
                cutout: '65%',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right' }
                }
            }
        });
    },

    async loadAuditLog() {
        const tbody = document.querySelector('#recent-audit-table tbody');
        try {
            // Using the mock telemetry/audit integration format endpoint
            // If it doesn't exist yet, we show empty state gracefully
            const audits = await App.apiGet('/api/v1/runbooks/executions').catch(() => []);
            
            if (!audits || audits.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="empty-state" style="padding:20px;">No recent audit logs available.</td></tr>';
                return;
            }

            tbody.innerHTML = audits.slice(0, 5).map(a => `
                <tr>
                    <td>${App.formatDate(a.started_at)}</td>
                    <td>${a.runbook_name || '-'}</td>
                    <td>Execution</td>
                    <td>${a.executed_by || 'system'}</td>
                    <td><span class="badge ${a.status === 'completed' ? 'badge-success' : 'badge-warning'}">${a.status}</span></td>
                </tr>
            `).join('');
        } catch(e) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center">Error loading audit logs.</td></tr>';
        }
    }
};
