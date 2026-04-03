/**
 * Device Management Panel
 * Lists inventory, provides health status, and access to interfaces.
 */

const DevicesPanel = {
    async init() {
        this.container = document.getElementById('panel-devices');
        this.renderSkeleton();
        await this.loadData();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>Device Inventory</h3>
                    <div class="header-actions">
                        <button class="btn btn-outline btn-sm" onclick="DevicesPanel.loadData()"><span class="material-icons-outlined">refresh</span> Refresh</button>
                        <button class="btn btn-primary btn-sm"><span class="material-icons-outlined">add</span> Discover Device</button>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table id="devices-table">
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>Hostname</th>
                                <th>Management IP</th>
                                <th>Role</th>
                                <th>Model & OS</th>
                                <th>Site / Pod</th>
                                <th>Sync Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="8" class="empty-state">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    },

    async loadData() {
        const tbody = document.querySelector('#devices-table tbody');
        try {
            const devices = await App.apiGet('/api/v1/devices');
            
            if (!devices || devices.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" class="empty-state" style="padding: 60px 20px;">
                            <span class="material-icons-outlined" style="font-size:48px; color:var(--border);">dns</span>
                            <h4>No Devices Found</h4>
                            <p>No devices have been discovered or onboarded via ZTP yet.</p>
                        </td>
                    </tr>
                `;
                return;
            }

            tbody.innerHTML = devices.map(d => `
                <tr>
                    <td>${this.getStatusBadge(d.status)}</td>
                    <td style="font-weight:600;">${d.hostname}</td>
                    <td>${d.management_ip}</td>
                    <td><span class="badge badge-neutral">${d.role}</span></td>
                    <td>${d.model}<br><span style="font-size:11px; color:var(--text-muted);">${d.software_version}</span></td>
                    <td>${d.site} / ${d.pod}</td>
                    <td><span class="badge badge-success">In Sync</span></td>
                    <td>
                        <div class="table-actions">
                            <button class="btn-icon" title="View Interfaces" onclick="DevicesPanel.viewInterfaces('${d.id}')">
                                <span class="material-icons-outlined">settings_input_component</span>
                            </button>
                            <button class="btn-icon" title="View Configuration" onclick="DevicesPanel.viewConfig('${d.id}')">
                                <span class="material-icons-outlined">code</span>
                            </button>
                        </div>
                    </td>
                </tr>
            `).join('');

        } catch (error) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--danger)">Failed to load devices</td></tr>';
            App.showToast("Error", "Could not load device inventory", "error");
        }
    },

    getStatusBadge(status) {
        switch(status.toLowerCase()) {
            case 'active': return '<span class="status-dot active" title="Active"></span> <span style="font-size:12px;">Active</span>';
            case 'degraded': return '<span class="status-dot degraded" title="Degraded"></span> <span style="font-size:12px;">Degraded</span>';
            case 'offline': return '<span class="status-dot offline" title="Offline"></span> <span style="font-size:12px;">Offline</span>';
            case 'provisioning': return '<span class="status-dot unknown" title="Provisioning"></span> <span style="font-size:12px;">Syncing</span>';
            default: return `<span class="status-dot unknown"></span> <span style="font-size:12px;">${status}</span>`;
        }
    },

    async viewInterfaces(deviceId) {
        try {
            const device = await App.apiGet(`/api/v1/devices/${deviceId}`);
            const interfaces = device.interfaces || [];

            let html = `
                <table style="margin-top:16px;">
                    <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>IP/MAC</th><th>Description</th></tr></thead>
                    <tbody>
            `;
            
            if (interfaces.length === 0) {
                html += '<tr><td colspan="5" style="text-align:center;">No interfaces configured</td></tr>';
            } else {
                html += interfaces.map(i => `
                    <tr>
                        <td style="font-weight:500;">${i.name}</td>
                        <td>${i.type}</td>
                        <td><span class="badge ${i.status.toLowerCase()==='up'?'badge-success':'badge-danger'}">${i.status.toUpperCase()}</span></td>
                        <td>${i.ip_address || '-'}<br><span style="font-size:11px;color:var(--text-muted);">${i.mac_address||'-'}</span></td>
                        <td>${i.description || '-'}</td>
                    </tr>
                `).join('');
            }
            
            html += '</tbody></table>';

            App.showModal(`Interfaces: ${device.hostname}`, html);
        } catch(e) {
            App.showToast("Error", "Could not load interfaces", "error");
        }
    },

    async viewConfig(deviceId) {
        try {
            // Simulated config fetch. In a real app, query the config_audit or live NETCONF get-config
            App.showModal("Configuration Viewer", `
                <div class="code-editor" readonly>
&lt;!-- Running Configuration --&gt;
&lt;sysname&gt;device_hostname&lt;/sysname&gt;
&lt;interfaces&gt;
    &lt;interface&gt;
        &lt;name&gt;10GE1/0/1&lt;/name&gt;
        &lt;description&gt;To_Spine_1&lt;/description&gt;
        &lt;ipv4&gt;10.0.0.1 255.255.255.252&lt;/ipv4&gt;
    &lt;/interface&gt;
&lt;/interfaces&gt;
                </div>
            `);
        } catch(e) {}
    }
};
