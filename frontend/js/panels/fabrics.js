/**
 * Fabric Management Panel
 * Lists manageable VXLAN fabrics, underlay/overlay status.
 */

const FabricsPanel = {
    async init() {
        this.container = document.getElementById('panel-fabrics');
        this.renderSkeleton();
        await this.loadData();
    },

    renderSkeleton() {
        this.container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>VXLAN Fabrics</h3>
                    <div class="header-actions">
                        <button class="btn btn-outline btn-sm" onclick="FabricsPanel.loadData()"><span class="material-icons-outlined">refresh</span> Refresh</button>
                        <button class="btn btn-primary btn-sm" onclick="FabricsPanel.createFabric()"><span class="material-icons-outlined">add</span> Create Fabric</button>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table id="fabrics-table">
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>Fabric Name</th>
                                <th>BGP ASN</th>
                                <th>Spines</th>
                                <th>Leaves</th>
                                <th>Underlay Status</th>
                                <th>Overlay Status</th>
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
        const tbody = document.querySelector('#fabrics-table tbody');
        try {
            const fabrics = await App.apiGet('/api/v1/fabrics');
            
            if (!fabrics || fabrics.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" class="empty-state" style="padding: 60px 20px;">
                            <span class="material-icons-outlined" style="font-size:48px; color:var(--border);">lan</span>
                            <h4>No Fabrics Defined</h4>
                            <p>Create a fabric to start assigning devices and provisioning overlays.</p>
                        </td>
                    </tr>
                `;
                return;
            }

            tbody.innerHTML = fabrics.map(f => `
                <tr>
                    <td>${this.getStatusBadge(f.status)}</td>
                    <td style="font-weight:600;">${f.name}</td>
                    <td>AS ${f.bgp_asn || 'N/A'}</td>
                    <td>${f.device_roles ? Object.values(f.device_roles).filter(r => r === 'spine').length : 0}</td>
                    <td>${f.device_roles ? Object.values(f.device_roles).filter(r => r.includes('leaf')).length : 0}</td>
                    <td><span class="badge ${f.underlay_status==='active'?'badge-success':'badge-warning'}">OSPF ${f.underlay_status}</span></td>
                    <td><span class="badge ${f.overlay_status==='active'?'badge-success':'badge-warning'}">EVPN ${f.overlay_status}</span></td>
                    <td>
                        <div class="table-actions">
                            <button class="btn-icon" title="Deploy Underlay/Overlay">
                                <span class="material-icons-outlined">cloud_upload</span>
                            </button>
                            <button class="btn-icon" title="Edit Fabric">
                                <span class="material-icons-outlined">edit</span>
                            </button>
                            <button class="btn-icon" title="Delete Fabric" style="color:var(--danger)">
                                <span class="material-icons-outlined">delete</span>
                            </button>
                        </div>
                    </td>
                </tr>
            `).join('');

        } catch (error) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--danger)">Failed to load fabrics</td></tr>';
            App.showToast("Error", "Could not load fabrics", "error");
        }
    },

    getStatusBadge(status) {
        if (!status) return `<span class="status-dot unknown"></span> <span style="font-size:12px;">Unknown</span>`;
        switch(status.toLowerCase()) {
            case 'active': return '<span class="status-dot active"></span> <span style="font-size:12px;">Active</span>';
            case 'provisioning': return '<span class="status-dot unknown"></span> <span style="font-size:12px;">Deploying</span>';
            case 'failed': return '<span class="status-dot offline"></span> <span style="font-size:12px;">Deployment Failed</span>';
            default: return `<span class="status-dot degraded"></span> <span style="font-size:12px;">${status}</span>`;
        }
    },

    createFabric() {
        const html = `
            <form id="create-fabric-form">
                <div class="form-group">
                    <label>Fabric Name</label>
                    <input type="text" id="fab-name" required placeholder="e.g. DC1-Fabric">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>BGP ASN</label>
                        <input type="number" id="fab-asn" required placeholder="65000">
                    </div>
                    <div class="form-group">
                        <label>Underlay Routing</label>
                        <select id="fab-underlay">
                            <option value="ospf">OSPFv2</option>
                            <option value="ebgp">eBGP</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea id="fab-desc"></textarea>
                </div>
            </form>
        `;
        
        const footer = `
            <button class="btn btn-outline" onclick="App.closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="FabricsPanel.submitFabric()">Create</button>
        `;
        
        App.showModal("Create New Fabric", html, footer);
    },

    async submitFabric() {
        const payload = {
            name: document.getElementById('fab-name').value,
            bgp_asn: parseInt(document.getElementById('fab-asn').value),
            description: document.getElementById('fab-desc').value,
            status: 'draft'
        };

        try {
            await App.apiPost('/api/v1/fabrics', payload);
            App.closeModal();
            App.showToast("Success", "Fabric created successfully", "success");
            this.loadData();
        } catch(e) {
            App.showToast("Error", "Failed to create fabric. " + e.message, "error");
        }
    }
};
