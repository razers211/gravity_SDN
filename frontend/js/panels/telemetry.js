/**
 * Telemetry Dashboard Panel
 * Interface statistics, CPU/Memory gauges via Chart.js
 */

const TelemetryPanel = {
    async init() {
        this.container = document.getElementById('panel-telemetry');
        this.renderSkeleton();
        
        setTimeout(() => this.initCharts(), 50);
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card" style="margin-bottom:24px;">
                <div class="card-header">
                    <h3>Fabric Telemetry Overview</h3>
                    <div class="header-actions">
                        <select class="filter-select" id="tel-timeframe">
                            <option value="1h">Last 1 Hour</option>
                            <option value="6h">Last 6 Hours</option>
                            <option value="24h">Last 24 Hours</option>
                        </select>
                        <button class="btn btn-outline btn-sm"><span class="material-icons-outlined">refresh</span> Refresh</button>
                    </div>
                </div>
                <div class="card-body">
                    <div class="grid-2">
                        <div>
                            <h4 style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">Spine Uplink Utilization (Gbps)</h4>
                            <div class="chart-container">
                                <canvas id="chart-traffic"></canvas>
                            </div>
                        </div>
                        <div>
                            <h4 style="margin-bottom:12px; font-size:13px; color:var(--text-secondary);">Fabric CPU & Memory Trend (%)</h4>
                            <div class="chart-container">
                                <canvas id="chart-resources"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3>Device Metrics (Real-time)</h3>
                </div>
                <div class="table-wrapper">
                    <table id="telemetry-table">
                        <thead>
                            <tr>
                                <th>Device</th>
                                <th>Role</th>
                                <th>CPU Util</th>
                                <th>Memory Util</th>
                                <th>Temperature</th>
                                <th>Drops/Errors</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="6" class="empty-state">Loading metrics...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    },

    async initCharts() {
        // Fetch devices to populate the table
        this.loadTableData();

        // 1. Traffic Chart (Area Line)
        const ctxTraffic = document.getElementById('chart-traffic').getContext('2d');
        
        // Generate mock timeline data for the charts (since we have no real time-series DB connected yet)
        const labels = Array.from({length: 12}, (_, i) => `T-${11-i}m`);
        const txData = labels.map(() => Math.floor(Math.random() * 40) + 10);
        const rxData = labels.map(() => Math.floor(Math.random() * 30) + 5);

        new Chart(ctxTraffic, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'TX Traffic (Gbps)',
                        data: txData,
                        borderColor: '#0066cc',
                        backgroundColor: 'rgba(0, 102, 204, 0.1)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'RX Traffic (Gbps)',
                        data: rxData,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        fill: true,
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true } },
                plugins: { legend: { position: 'top' } }
            }
        });

        // 2. Resource Chart (Line)
        const ctxRes = document.getElementById('chart-resources').getContext('2d');
        const cpuData = labels.map(() => Math.floor(Math.random() * 20) + 10);
        const memData = labels.map(() => Math.floor(Math.random() * 10) + 40);

        new Chart(ctxRes, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Avg CPU (%)',
                        data: cpuData,
                        borderColor: '#ea580c',
                        backgroundColor: '#ea580c',
                        tension: 0.2
                    },
                    {
                        label: 'Avg Memory (%)',
                        data: memData,
                        borderColor: '#8b5cf6',
                        backgroundColor: '#8b5cf6',
                        tension: 0.2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true, max: 100 } }
            }
        });
    },

    async loadTableData() {
        const tbody = document.querySelector('#telemetry-table tbody');
        try {
            const devices = await App.apiGet('/api/v1/devices');
            
            if (!devices || devices.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No telemetry data available</td></tr>';
                return;
            }

            tbody.innerHTML = devices.map(d => {
                // Generate mock stats for visual completeness since we don't store live stats in the DB
                const cpu = Math.floor(Math.random() * 40) + 5;
                const mem = Math.floor(Math.random() * 30) + 30;
                const temp = Math.floor(Math.random() * 20) + 35;
                
                return `
                    <tr>
                        <td style="font-weight:500;">${d.hostname}</td>
                        <td>${d.role}</td>
                        <td>
                            <div class="utilization-cell">
                                <div class="progress-bar"><div class="progress-bar-fill ${cpu>80?'red':(cpu>60?'yellow':'blue')}" style="width:${cpu}%"></div></div>
                                <span>${cpu}%</span>
                            </div>
                        </td>
                        <td>
                            <div class="utilization-cell">
                                <div class="progress-bar"><div class="progress-bar-fill ${mem>80?'red':(mem>60?'yellow':'blue')}" style="width:${mem}%"></div></div>
                                <span>${mem}%</span>
                            </div>
                        </td>
                        <td>${temp} °C</td>
                        <td>0 / 0</td>
                    </tr>
                `;
            }).join('');
        } catch(e) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--danger)">Error loading metrics</td></tr>';
        }
    }
};
