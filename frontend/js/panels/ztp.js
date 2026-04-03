/**
 * Zero Touch Provisioning (ZTP) Panel
 * DHCP listener status, ESN registration, and deployment progress.
 */

const ZtpPanel = {
    async init() {
        this.container = document.getElementById('panel-ztp');
        this.renderSkeleton();
        await this.loadData();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>ZTP Device Onboarding</h3>
                    <div class="header-actions">
                        <button class="btn btn-outline btn-sm" onclick="ZtpPanel.loadData()"><span class="material-icons-outlined">refresh</span> Refresh</button>
                        <button class="btn btn-primary btn-sm" onclick="ZtpPanel.registerESN()"><span class="material-icons-outlined">add</span> Pre-register ESN</button>
                    </div>
                </div>
                <div class="card-body" style="padding-bottom:0;">
                    <div style="display:flex; gap:24px; margin-bottom:20px; align-items:center; background:var(--bg-primary); padding:12px 16px; border-radius:var(--radius-sm); border:1px solid var(--border);">
                        <div>
                            <span style="font-size:12px; color:var(--text-secondary); text-transform:uppercase;">DHCP Listener</span><br>
                            <span style="font-weight:600; color:var(--success);"><span class="status-dot active"></span> Active on port 67</span>
                        </div>
                        <div style="width:1px; height:30px; background:var(--border);"></div>
                        <div>
                            <span style="font-size:12px; color:var(--text-secondary); text-transform:uppercase;">Discovered Devices</span><br>
                            <span style="font-weight:600;" id="ztp-count">0</span>
                        </div>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table id="ztp-table">
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>ESN (Serial)</th>
                                <th>MAC Address</th>
                                <th>Assigned IP</th>
                                <th>Auth Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="6" class="empty-state">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    },

    async loadData() {
        const tbody = document.querySelector('#ztp-table tbody');
        try {
            const ztpDevices = await App.apiGet('/api/v1/ztp/discovered');
            document.getElementById('ztp-count').textContent = ztpDevices.length;
            
            if (!ztpDevices || ztpDevices.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="empty-state" style="padding: 60px 20px;">
                            <span class="material-icons-outlined" style="font-size:48px; color:var(--text-muted);">router</span>
                            <h4>No Devices Discovered</h4>
                            <p>Waiting for new CloudEngine devices to broadcast DHCP DISCOVER.</p>
                        </td>
                    </tr>
                `;
                return;
            }

            tbody.innerHTML = ztpDevices.map(d => `
                <tr>
                    <td>${this.getStatusBadge(d.status)}</td>
                    <td style="font-family:monospace; font-size:13px;">${d.esn}</td>
                    <td>${d.mac_address || '-'}</td>
                    <td>${d.assigned_ip || '-'}</td>
                    <td><span class="badge ${d.is_authenticated ? 'badge-success' : 'badge-warning'}">${d.is_authenticated ? 'Verified' : 'Pending'}</span></td>
                    <td>
                        <button class="btn btn-outline btn-sm" ${d.status === 'completed' ? 'disabled' : ''} onclick="ZtpPanel.retryDevice('${d.esn}')">Retry Deploy</button>
                    </td>
                </tr>
            `).join('');

        } catch (error) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--danger)">Failed to load ZTP queue</td></tr>';
        }
    },

    getStatusBadge(status) {
        switch(status.toLowerCase()) {
            case 'discovered': return '<span class="status-dot unknown"></span> <span style="font-size:12px;">Discovered</span>';
            case 'authenticating': return '<span class="status-dot unknown"></span> <span style="font-size:12px;">Auth In Progress</span>';
            case 'deploying': return '<span class="badge badge-info">Deploying Baseline</span>';
            case 'completed': return '<span class="status-dot active"></span> <span style="font-size:12px;">Completed</span>';
            case 'failed': return '<span class="status-dot offline"></span> <span style="font-size:12px;">Failed</span>';
            default: return `<span class="badge badge-neutral">${status}</span>`;
        }
    },

    registerESN() {
        const html = `
            <form id="register-esn-form">
                <div class="form-group">
                    <label>Equipment Serial Number (ESN)</label>
                    <input type="text" id="reg-esn" required placeholder="e.g. 2102311TDN10L6000003">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Hostname</label>
                        <input type="text" id="reg-hostname" required placeholder="e.g. ce-leaf-01">
                    </div>
                    <div class="form-group">
                        <label>Role</label>
                        <select id="reg-role">
                            <option value="spine">Spine</option>
                            <option value="leaf" selected>Leaf</option>
                            <option value="border-leaf">Border Leaf</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>Management IP (Static Override)</label>
                    <input type="text" id="reg-ip" placeholder="Leave blank for DHCP allocation">
                </div>
            </form>
        `;
        
        const footer = `
            <button class="btn btn-outline" onclick="App.closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="ZtpPanel.submitESN()">Register</button>
        `;
        
        App.showModal("Pre-Register Device ESN", html, footer);
    },

    async submitESN() {
        const payload = {
            esn: document.getElementById('reg-esn').value,
            hostname: document.getElementById('reg-hostname').value,
            role: document.getElementById('reg-role').value,
            target_ip: document.getElementById('reg-ip').value || null
        };

        try {
            await App.apiPost('/api/v1/ztp/register', payload);
            App.closeModal();
            App.showToast("Success", `ESN ${payload.esn} registered`, "success");
            this.loadData();
        } catch(e) {
            App.showToast("Error", "Failed to register ESN", "error");
        }
    },

    async retryDevice(esn) {
        try {
            await App.apiPost(`/api/v1/ztp/${esn}/retry`);
            App.showToast("Success", "Retrying deployment", "success");
            this.loadData();
        } catch(e) {
            App.showToast("Error", "Failed to retry", "error");
        }
    }
};
